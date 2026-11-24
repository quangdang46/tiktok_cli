package com.tiktoksummarizer

import java.io.RandomAccessFile

object WavUtil {

    const val SAMPLE_RATE = 16000
    const val CHANNELS = 1
    const val BITS = 16

    /**
     * Writes a WAV file incrementally: header placeholder first,
     * patch sizes on close. PCM data is appended raw.
     */
    class Writer(file: java.io.File) {
        private val raf = RandomAccessFile(file, "rw")
        private var dataBytes = 0L

        init {
            raf.setLength(44)
        }

        fun write(pcm: ByteArray, len: Int) {
            raf.seek(44 + dataBytes)
            raf.write(pcm, 0, len)
            dataBytes += len
        }

        fun close() {
            writeHeader()
            raf.close()
        }

        private fun writeHeader() {
            val byteRate = SAMPLE_RATE * CHANNELS * BITS / 8
            val blockAlign = CHANNELS * BITS / 8
            val total = 36 + dataBytes
            raf.seek(0)
            raf.writeBytes("RIFF")
            raf.writeIntLe(total.toInt())
            raf.writeBytes("WAVE")
            raf.writeBytes("fmt ")
            raf.writeIntLe(16)              // fmt chunk size
            raf.writeShortLe(1)             // PCM
            raf.writeShortLe(CHANNELS)
            raf.writeIntLe(SAMPLE_RATE)
            raf.writeIntLe(byteRate)
            raf.writeShortLe(blockAlign)
            raf.writeShortLe(BITS)
            raf.writeBytes("data")
            raf.writeIntLe(dataBytes.toInt())
        }
    }
}

private fun RandomAccessFile.writeIntLe(v: Int) {
    write(v and 0xFF); write((v shr 8) and 0xFF); write((v shr 16) and 0xFF); write((v shr 24) and 0xFF)
}
private fun RandomAccessFile.writeShortLe(v: Int) {
    write(v and 0xFF); write((v shr 8) and 0xFF)
}
