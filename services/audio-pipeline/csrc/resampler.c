/*
 * PROP-103: Bidirectional 8kHz G.711 mu-law <-> 16kHz PCM16 audio pipeline.
 *
 * The mu-law DECODE table below is the standard ITU-T G.711 formula
 * (the classic public-domain reference algorithm reproduced across most
 * telephony codebases) -- this must match the real-world standard exactly,
 * since it's what makes real Twilio audio decode correctly.
 *
 * The mu-law ENCODE step is deliberately NOT a separately hand-written
 * bit-manipulation routine (those are easy to get subtly wrong and have
 * it silently diverge from the decoder). Instead it does a nearest-value
 * search against the same 256-entry decode table: by definition, mu-law
 * encoding of a sample is "which of the 256 representable codes decodes
 * closest to this value" -- so building the encoder directly from the
 * verified decoder guarantees they can never disagree with each other.
 */

#include <stdint.h>
#include <stdlib.h>

#define ULAW_BIAS 0x84

static int16_t decode_table[256];
static struct {
    int16_t value;
    uint8_t code;
} sorted_table[256];
static int tables_ready = 0;

static int16_t ulaw_decode_sample(uint8_t u_val) {
    uint8_t u = (uint8_t)(~u_val);
    int sign = u & 0x80;
    int exponent = (u & 0x70) >> 4;
    int mantissa = u & 0x0F;
    int t = ((mantissa << 3) + ULAW_BIAS) << exponent;
    return (int16_t)(sign ? (ULAW_BIAS - t) : (t - ULAW_BIAS));
}

static void init_tables(void) {
    int i, j;
    if (tables_ready) return;

    /* Not thread-safe by itself (plain int flag, no lock/atomic) -- safe in
     * practice only because __attribute__((constructor)) below runs this to
     * completion at library-load time, before any thread can reach the
     * public API functions that call init_tables(). Do not remove that
     * constructor call without adding real synchronization here: with
     * multiple threads racing this function directly (e.g. via ctypes from
     * several Python threads at once, which release the GIL during the
     * call), the check-then-fill-then-set-flag sequence can interleave and
     * hand back a torn/partially-initialized table. */
    for (i = 0; i < 256; i++) {
        int16_t v = ulaw_decode_sample((uint8_t)i);
        decode_table[i] = v;
        sorted_table[i].value = v;
        sorted_table[i].code = (uint8_t)i;
    }

    /* insertion sort by value -- 256 elements, done once, negligible cost */
    for (i = 1; i < 256; i++) {
        int16_t val = sorted_table[i].value;
        uint8_t code = sorted_table[i].code;
        j = i - 1;
        while (j >= 0 && sorted_table[j].value > val) {
            sorted_table[j + 1] = sorted_table[j];
            j--;
        }
        sorted_table[j + 1].value = val;
        sorted_table[j + 1].code = code;
    }

    tables_ready = 1;
}

/* Force table initialization at library-load time (single-threaded, before
 * any caller can reach ulaw_to_pcm16/pcm16_to_ulaw), so the lazy check in
 * init_tables() above is always a no-op read in practice and concurrent
 * calls from multiple threads can never race the fill loop. Supported by
 * both GCC and Clang on macOS/Linux, the two platforms build.sh targets. */
__attribute__((constructor))
static void init_tables_at_load(void) {
    init_tables();
}

static uint8_t ulaw_encode_sample(int16_t pcm) {
    int lo = 0, hi = 255, mid, best;
    init_tables();

    while (lo < hi) {
        mid = (lo + hi) / 2;
        if (sorted_table[mid].value < pcm) lo = mid + 1;
        else hi = mid;
    }
    best = lo;
    if (lo > 0) {
        int diff_lo = abs((int)sorted_table[lo].value - (int)pcm);
        int diff_prev = abs((int)sorted_table[lo - 1].value - (int)pcm);
        if (diff_prev <= diff_lo) best = lo - 1;
    }
    return sorted_table[best].code;
}

/* ---- Public API (called from Python via ctypes) ---- */

void ulaw_to_pcm16(const uint8_t *ulaw, int n, int16_t *pcm_out) {
    int i;
    init_tables();
    for (i = 0; i < n; i++) pcm_out[i] = decode_table[ulaw[i]];
}

void pcm16_to_ulaw(const int16_t *pcm, int n, uint8_t *ulaw_out) {
    int i;
    init_tables();
    for (i = 0; i < n; i++) ulaw_out[i] = ulaw_encode_sample(pcm[i]);
}

/* 8kHz -> 16kHz via linear interpolation. out must hold 2*n samples. */
void upsample_2x(const int16_t *in, int n, int16_t *out) {
    int i;
    if (n <= 0) return;
    for (i = 0; i < n; i++) {
        int16_t next = (i + 1 < n) ? in[i + 1] : in[i];
        out[2 * i] = in[i];
        out[2 * i + 1] = (int16_t)(((int)in[i] + (int)next) / 2);
    }
}

/* 16kHz -> 8kHz via pairwise averaging (box-car low-pass + decimate).
   n must be even; out must hold n/2 samples. */
void downsample_2x(const int16_t *in, int n, int16_t *out) {
    int i, out_n = n / 2;
    for (i = 0; i < out_n; i++) {
        out[i] = (int16_t)(((int)in[2 * i] + (int)in[2 * i + 1]) / 2);
    }
}
