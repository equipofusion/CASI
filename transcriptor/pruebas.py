#!/usr/bin/env python3
"""Pruebas de la plomería, sin necesidad de descargar ningún modelo.

Verifican decodificación de audio, armado de bloques por hablante, formatos de
salida, registro de estado y detección de archivos del vigía. No cubren la
transcripción ni la diarización en sí, que dependen de los pesos de Whisper y
pyannote.

    ./.venv/bin/python pruebas.py
"""
from __future__ import annotations

import math
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import asr
import audio
import config
import salida
import vigilar
from asr import Palabra
from estado import Estado
from parcial import Parcial
from hablantes import SIN_IDENTIFICAR, Turno, _como_anotacion, asignar


def _generar_audio(destino: Path, segundos: float = 3.0, tasa: int = 44_100) -> None:
    """Escribe un tono de prueba, en un contenedor distinto al de salida."""
    import av
    import numpy as np

    with av.open(str(destino), "w") as contenedor:
        pista = contenedor.add_stream("aac", rate=tasa)
        pista.layout = "stereo"

        total = int(tasa * segundos)
        bloque = 1024
        fase = 0
        while fase < total:
            n = min(bloque, total - fase)
            t = (np.arange(fase, fase + n) / tasa).astype(np.float32)
            onda = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
            estereo = np.vstack([onda, onda])

            cuadro = av.AudioFrame.from_ndarray(estereo, format="fltp", layout="stereo")
            cuadro.rate = tasa
            cuadro.pts = fase
            for paquete in pista.encode(cuadro):
                contenedor.mux(paquete)
            fase += n

        for paquete in pista.encode(None):
            contenedor.mux(paquete)


class PruebasAudio(unittest.TestCase):
    def test_extrae_wav_mono_16k_con_duracion_correcta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen = Path(tmp) / "tono.m4a"
            destino = Path(tmp) / "salida.wav"
            _generar_audio(origen, segundos=3.0)

            duracion = audio.extraer_wav(origen, destino)

            self.assertTrue(destino.is_file())
            self.assertAlmostEqual(duracion, 3.0, delta=0.25)

            import wave
            with wave.open(str(destino)) as leido:
                self.assertEqual(leido.getnchannels(), 1)
                self.assertEqual(leido.getframerate(), 16_000)
                self.assertEqual(leido.getsampwidth(), 2)

    def test_archivo_sin_audio_da_error_claro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vacio = Path(tmp) / "vacio.wav"
            vacio.write_bytes(b"no soy un contenedor valido")
            with self.assertRaises(Exception):
                audio.extraer_wav(vacio, Path(tmp) / "x.wav")

    def test_formato_de_duracion(self) -> None:
        self.assertEqual(audio.formatear_duracion(45), "45s")
        self.assertEqual(audio.formatear_duracion(125), "2m 05s")
        self.assertEqual(audio.formatear_duracion(3852), "1h 04m 12s")


class PruebasLecturaPorTramos(unittest.TestCase):
    """Una reunión de horas se lee por pedazos, no entera en memoria."""

    def _wav_de(self, carpeta: Path, segundos: float) -> Path:
        origen = carpeta / "largo.m4a"
        destino = carpeta / "largo.wav"
        _generar_audio(origen, segundos=segundos)
        audio.extraer_wav(origen, destino)
        return destino

    def test_duracion_del_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._wav_de(Path(tmp), 6.0)
            self.assertAlmostEqual(asr.duracion_wav(wav), 6.0, delta=0.3)

    def test_lee_solo_el_tramo_pedido(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._wav_de(Path(tmp), 6.0)

            tramo = asr.leer_tramo(wav, inicio=2.0, duracion=2.0)

            self.assertAlmostEqual(len(tramo) / asr.TASA, 2.0, delta=0.05)
            self.assertEqual(tramo.dtype.name, "float32")
            self.assertLessEqual(abs(tramo).max(), 1.0)

    def test_tramo_que_excede_el_final_devuelve_lo_que_queda(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._wav_de(Path(tmp), 3.0)

            tramo = asr.leer_tramo(wav, inicio=2.0, duracion=600.0)

            self.assertGreater(len(tramo), 0)
            self.assertLess(len(tramo) / asr.TASA, 1.5)

    def test_tramo_despues_del_final_es_vacio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = self._wav_de(Path(tmp), 2.0)

            self.assertEqual(len(asr.leer_tramo(wav, inicio=99.0, duracion=10.0)), 0)


class PruebasAvanceGuardado(unittest.TestCase):
    """Lo que evita perder horas de trabajo cuando una corrida se corta."""

    def _origen(self, carpeta: Path, contenido: bytes = b"x" * 100) -> Path:
        ruta = carpeta / "Reunión Formaro.qta"
        ruta.write_bytes(contenido)
        return ruta

    def test_guarda_y_retoma(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen = self._origen(Path(tmp))
            parcial = Parcial(Path(tmp) / ".parciales", origen)

            self.assertEqual(parcial.cargar(), (0, [], ""))

            parcial.guardar(3, [Palabra(0.0, 1.0, "hola")], "es")
            hechos, palabras, idioma = Parcial(Path(tmp) / ".parciales", origen).cargar()

            self.assertEqual(hechos, 3)
            self.assertEqual([p.texto for p in palabras], ["hola"])
            self.assertEqual(idioma, "es")

    def test_si_el_origen_cambia_se_descarta_el_avance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen = self._origen(Path(tmp))
            parcial = Parcial(Path(tmp) / ".parciales", origen)
            parcial.guardar(5, [Palabra(0.0, 1.0, "hola")], "es")

            origen.write_bytes(b"y" * 999)  # reexportada: es otro audio

            self.assertEqual(Parcial(Path(tmp) / ".parciales", origen).cargar(), (0, [], ""))

    def test_avance_corrupto_no_rompe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen = self._origen(Path(tmp))
            parcial = Parcial(Path(tmp) / ".parciales", origen)
            parcial.ruta.parent.mkdir(parents=True, exist_ok=True)
            parcial.ruta.write_text("{roto", encoding="utf-8")

            self.assertEqual(parcial.cargar(), (0, [], ""))

    def test_limpiar_borra_avance_y_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen = self._origen(Path(tmp))
            parcial = Parcial(Path(tmp) / ".parciales", origen)
            parcial.guardar(1, [], "es")
            parcial.wav.write_bytes(b"audio")

            parcial.limpiar()

            self.assertFalse(parcial.ruta.exists())
            self.assertFalse(parcial.wav.exists())


class PruebasReanudacion(unittest.TestCase):
    """Una corrida de horas que se corta debe retomar, no empezar de cero."""

    def _config(self, carpeta: Path):
        base = config.Config(
            carpeta_vigilada=carpeta, carpeta_salida=carpeta / "salida",
            modelo="fake", idioma="es", computo="int8", hilos=2,
            minutos_por_tramo=1, prioridad_baja=False,
            intervalo_segundos=1, espera_estabilidad_segundos=0,
            diarizar=False, modelo_hablantes="x", dispositivo_diarizacion="cpu",
            min_hablantes=None, max_hablantes=None, formatos_salida=("txt",),
        )
        return base

    def _motor_falso(self, romper_en: int | None = None):
        """Motor que devuelve una palabra por tramo, y puede fallar en uno."""
        llamadas = {"n": 0}

        class MotorFalso:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def transcribir_tramo(self, muestras, *, idioma, desplazamiento=0.0):
                llamadas["n"] += 1
                if romper_en is not None and llamadas["n"] == romper_en:
                    raise RuntimeError("se cortó la corrida")
                return [Palabra(desplazamiento, desplazamiento + 1.0, f"t{int(desplazamiento)}")], "es"

        return MotorFalso, llamadas

    def test_retoma_desde_el_tramo_donde_se_corto(self) -> None:
        from unittest.mock import patch
        import proceso

        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            origen = carpeta / "Reunión larga.m4a"
            _generar_audio(origen, segundos=150.0, tasa=16_000)  # 3 tramos de 1 min
            cfg = self._config(carpeta)

            # Primera corrida: se rompe en el segundo tramo.
            MotorFalso, llamadas = self._motor_falso(romper_en=2)
            with patch("asr.Motor", MotorFalso):
                with self.assertRaises(proceso.ErrorDeProceso):
                    proceso.transcribir_archivo(origen, cfg)

            parcial = Parcial(cfg.carpeta_salida / ".parciales", origen)
            hechos, palabras, _ = parcial.cargar()
            self.assertEqual(hechos, 1, "debió guardar el primer tramo")
            self.assertEqual(len(palabras), 1)
            self.assertTrue(parcial.wav.is_file(), "el WAV se conserva para retomar")

            # Segunda corrida: retoma y termina.
            MotorFalso, llamadas = self._motor_falso()
            with patch("asr.Motor", MotorFalso):
                generados = proceso.transcribir_archivo(origen, cfg)

            self.assertEqual(llamadas["n"], 2, "solo debía procesar los tramos que faltaban")
            texto = generados[0].read_text(encoding="utf-8")
            for esperado in ("t0", "t60", "t120"):
                self.assertIn(esperado, texto, "faltan palabras de algún tramo")

            self.assertFalse(parcial.ruta.exists(), "al terminar se limpia el avance")
            self.assertFalse(parcial.wav.exists())


class PruebasHilos(unittest.TestCase):
    def test_deja_nucleos_libres(self) -> None:
        hilos = config._hilos_por_defecto()

        self.assertGreaterEqual(hilos, 1)
        self.assertLessEqual(hilos, max(1, (os.cpu_count() or 4) - 2))


class PruebasAsignacionDeHablantes(unittest.TestCase):
    def test_agrupa_palabras_en_intervenciones(self) -> None:
        palabras = [
            Palabra(0.0, 0.5, "Hola"), Palabra(0.5, 1.0, "Juan"),
            Palabra(2.0, 2.5, "Qué"), Palabra(2.5, 3.0, "tal"),
            Palabra(4.0, 4.5, "Todo"), Palabra(4.5, 5.0, "bien"),
        ]
        turnos = [
            Turno(0.0, 1.2, "SPEAKER_00"),
            Turno(1.9, 3.2, "SPEAKER_01"),
            Turno(3.9, 5.2, "SPEAKER_00"),
        ]

        bloques = asignar(palabras, turnos)

        self.assertEqual(len(bloques), 3)
        self.assertEqual(bloques[0].hablante, "Hablante 1")
        self.assertEqual(bloques[0].texto, "Hola Juan")
        self.assertEqual(bloques[1].hablante, "Hablante 2")
        self.assertEqual(bloques[2].hablante, "Hablante 1")

    def test_palabras_contiguas_del_mismo_hablante_se_fusionan(self) -> None:
        palabras = [Palabra(i * 0.5, i * 0.5 + 0.4, f"p{i}") for i in range(6)]
        turnos = [Turno(0.0, 5.0, "SPEAKER_00")]

        bloques = asignar(palabras, turnos)

        self.assertEqual(len(bloques), 1)
        self.assertEqual(len(bloques[0].palabras), 6)

    def test_palabra_fuera_de_todo_turno_cae_al_mas_cercano(self) -> None:
        palabras = [Palabra(9.0, 9.3, "eh")]
        turnos = [Turno(0.0, 5.0, "SPEAKER_00")]

        bloques = asignar(palabras, turnos)

        self.assertEqual(bloques[0].hablante, "Hablante 1")

    def test_sin_diarizacion_devuelve_un_solo_bloque(self) -> None:
        palabras = [Palabra(0.0, 1.0, "hola"), Palabra(1.0, 2.0, "mundo")]

        bloques = asignar(palabras, [])

        self.assertEqual(len(bloques), 1)
        self.assertEqual(bloques[0].hablante, SIN_IDENTIFICAR)

    def test_sin_palabras_no_rompe(self) -> None:
        self.assertEqual(asignar([], [Turno(0, 1, "SPEAKER_00")]), [])


class PruebasCompatibilidadPyannote(unittest.TestCase):
    """pyannote 4 devuelve DiarizeOutput; la 3.x devolvía la Annotation pelada."""

    class _Anotacion:
        def __init__(self, nombre: str) -> None:
            self.nombre = nombre

    def test_pyannote_4_prefiere_la_anotacion_sin_solapamientos(self) -> None:
        class DiarizeOutput:
            speaker_diarization = self._Anotacion("con solapamiento")
            exclusive_speaker_diarization = self._Anotacion("exclusiva")

        self.assertEqual(_como_anotacion(DiarizeOutput()).nombre, "exclusiva")

    def test_cae_a_speaker_diarization_si_no_hay_exclusiva(self) -> None:
        class DiarizeOutput:
            speaker_diarization = self._Anotacion("con solapamiento")

        self.assertEqual(_como_anotacion(DiarizeOutput()).nombre, "con solapamiento")

    def test_pyannote_3_devuelve_la_anotacion_tal_cual(self) -> None:
        anotacion = self._Anotacion("pelada")

        self.assertIs(_como_anotacion(anotacion), anotacion)


class PruebasSalida(unittest.TestCase):
    def setUp(self) -> None:
        palabras_a = [Palabra(0.0, 0.5, "Hola"), Palabra(0.5, 1.0, "equipo")]
        palabras_b = [Palabra(2.0, 2.5, "Buenas"), Palabra(2.5, 3.0, "tardes")]
        from hablantes import Bloque
        self.bloques = [Bloque("Hablante 1", palabras_a), Bloque("Hablante 2", palabras_b)]
        self.meta = salida.Metadatos(
            origen=Path("/tmp/Reunión Formaro.m4a"),
            duracion=3852.0,
            idioma="es",
            modelo="large-v3",
            con_hablantes=True,
            procesado=datetime(2026, 9, 7, 15, 30),
        )

    def test_escribe_los_tres_formatos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generados = salida.escribir_todo(
                Path(tmp), "reunion", self.bloques, self.meta, ("txt", "srt", "md")
            )
            self.assertEqual(len(generados), 3)
            for ruta in generados:
                self.assertTrue(ruta.is_file(), ruta)
                self.assertGreater(ruta.stat().st_size, 0)

    def test_txt_incluye_hablantes_y_marcas_de_tiempo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "r.txt"
            salida.escribir_txt(destino, self.bloques, self.meta)
            texto = destino.read_text(encoding="utf-8")

            self.assertIn("Hablante 1: Hola equipo", texto)
            self.assertIn("[00:00:02]", texto)
            self.assertIn("1h 04m 12s", texto)

    def test_srt_es_valido_y_numerado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "r.srt"
            salida.escribir_srt(destino, self.bloques, self.meta)
            texto = destino.read_text(encoding="utf-8")

            self.assertIn("00:00:00,000 --> 00:00:01,000", texto)
            self.assertTrue(texto.startswith("1\n"))
            self.assertIn("\n2\n", texto)

    def test_srt_corta_intervenciones_largas(self) -> None:
        from hablantes import Bloque
        largas = [Palabra(i * 1.0, i * 1.0 + 0.9, "palabra") for i in range(30)]
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "r.srt"
            salida.escribir_srt(destino, [Bloque("Hablante 1", largas)], self.meta)
            texto = destino.read_text(encoding="utf-8")

            # 30 segundos de habla continua no pueden ser un único subtítulo.
            self.assertGreater(texto.count("-->"), 3)

    def test_md_sin_diarizacion_omite_hablantes(self) -> None:
        from dataclasses import replace
        meta = replace(self.meta, con_hablantes=False)
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "r.md"
            salida.escribir_md(destino, self.bloques, meta)
            texto = destino.read_text(encoding="utf-8")

            self.assertNotIn("**Hablante 1**", texto)
            self.assertIn("Hola equipo", texto)


class PruebasEstado(unittest.TestCase):
    def test_recuerda_lo_procesado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "a.m4a"
            archivo.write_bytes(b"x" * 100)
            estado = Estado(Path(tmp) / "estado.json")

            self.assertFalse(estado.ya_procesado(archivo))
            estado.marcar(archivo, [Path(tmp) / "a.txt"])
            self.assertTrue(estado.ya_procesado(archivo))

            # Otra instancia lee lo mismo desde disco.
            self.assertTrue(Estado(Path(tmp) / "estado.json").ya_procesado(archivo))

    def test_archivo_modificado_se_reprocesa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "a.m4a"
            archivo.write_bytes(b"x" * 100)
            estado = Estado(Path(tmp) / "estado.json")
            estado.marcar(archivo, [])

            archivo.write_bytes(b"x" * 500)  # reexportado, cambia el tamaño
            self.assertFalse(estado.ya_procesado(archivo))

    def test_estado_corrupto_no_rompe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "estado.json"
            ruta.write_text("{esto no es json", encoding="utf-8")
            archivo = Path(tmp) / "a.m4a"
            archivo.write_bytes(b"x")

            self.assertFalse(Estado(ruta).ya_procesado(archivo))


class PruebasVigia(unittest.TestCase):
    def test_reconoce_formatos_de_quicktime_player(self) -> None:
        """QuickTime Player exporta .qta, no .m4a. Es un contenedor QuickTime."""
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "Reunión Formaro 3-9.qta").write_bytes(b"x")
            (carpeta / "voz.caf").write_bytes(b"x")

            nombres = {r.name for r in vigilar.candidatos(carpeta, carpeta / "salida")}

            self.assertEqual(nombres, {"Reunión Formaro 3-9.qta", "voz.caf"})

    def test_decodifica_un_contenedor_quicktime_con_extension_qta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mov = Path(tmp) / "grabacion.mov"
            _generar_audio(mov, segundos=2.0)
            qta = Path(tmp) / "Reunión Juan Formaro 3-9.qta"
            mov.rename(qta)

            duracion = audio.extraer_wav(qta, Path(tmp) / "salida.wav")

            self.assertAlmostEqual(duracion, 2.0, delta=0.25)

    def test_detecta_solo_medios_y_omite_ocultos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "vigilada"
            salida_dir = carpeta / "salida"
            salida_dir.mkdir(parents=True)

            (carpeta / "reunion.m4a").write_bytes(b"x")
            (carpeta / "video.mov").write_bytes(b"x")
            (carpeta / "notas.txt").write_bytes(b"x")
            (carpeta / ".oculto.m4a").write_bytes(b"x")
            (salida_dir / "vieja.mp3").write_bytes(b"x")

            nombres = {r.name for r in vigilar.candidatos(carpeta, salida_dir)}

            self.assertEqual(nombres, {"reunion.m4a", "video.mov"})

    def test_no_toma_un_archivo_que_sigue_creciendo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "a.m4a"
            archivo.write_bytes(b"x" * 10)
            visto: dict = {}

            # Primera vuelta: recién lo ve, nunca es estable todavía.
            self.assertFalse(vigilar.esta_estable(archivo, visto, espera=0))

            archivo.write_bytes(b"x" * 50)  # sigue copiándose
            self.assertFalse(vigilar.esta_estable(archivo, visto, espera=0))

            # Ya no cambia: con espera 0 se considera listo.
            self.assertTrue(vigilar.esta_estable(archivo, visto, espera=0))

    def test_respeta_la_ventana_de_espera(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "a.m4a"
            archivo.write_bytes(b"x" * 10)
            visto: dict = {}

            vigilar.esta_estable(archivo, visto, espera=600)
            self.assertFalse(vigilar.esta_estable(archivo, visto, espera=600))


if __name__ == "__main__":
    unittest.main(verbosity=2)
