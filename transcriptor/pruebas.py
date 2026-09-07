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
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import audio
import salida
import vigilar
from asr import Palabra
from estado import Estado
from hablantes import SIN_IDENTIFICAR, Turno, asignar


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
