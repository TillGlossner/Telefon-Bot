/*
 * AudioWorklet: schneidet das Mikrofonsignal in Bloecke und reicht sie weiter.
 *
 * Laeuft im Audio-Thread, damit die Aufnahme nicht ins Stocken geraet, wenn die
 * Oberflaeche beschaeftigt ist. Das Herunterrechnen auf 8 kHz passiert im
 * Hauptthread -- hier zaehlt nur, dass kein Block verloren geht.
 */
class Aufnahme extends AudioWorkletProcessor {
  process(eingaenge) {
    const kanal = eingaenge[0] && eingaenge[0][0];
    if (kanal && kanal.length) {
      this.port.postMessage(new Float32Array(kanal));
    }
    return true;
  }
}
registerProcessor("aufnahme", Aufnahme);
