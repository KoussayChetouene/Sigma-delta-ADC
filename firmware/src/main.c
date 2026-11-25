/*
 * sdm_f746 - 1st-order sigma-delta ADC prototype on the STM32F746G-DISCO
 * ======================================================================
 *
 * The analog loop filter (integrator + comparator, MCP6002) sits on the
 * breadboard. This firmware closes the loop and plays the roles a real
 * sigma-delta chip would have on-die:
 *
 *   - clocked latch:  TIM1 update interrupt at fs = 50 kHz samples the comparator
 *   - 1-bit DAC:      a GPIO drives the feedback resistor, FB = latched bit
 *   - decimator:      real-time CIC (K = 3, R = 64) -> 781.25 S/s, bit-exact with sdm/cic.py
 *   - test source:    the DAC pins (PA4/PA5) are not on the Disco headers, so the
 *                     test sine is a PWM on TIM1_CH1 (same 50 kHz period, so the PWM
 *                     ripple aliases to DC) driven by a 32-bit DDS with first-order
 *                     error feedback on the duty cycle (noise-shaped PWM DAC)
 *
 * Pins (Arduino headers of the Disco):
 *   D7  = PI3  -> FB   (to the 10 k feedback resistor)
 *   D4  = PG7  <- CMP  (MCP6002 pin 7, comparator output)
 *   D10 = PA8  -> PWM  (TIM1_CH1 -> 1k/100nF -> 1k/100nF -> 10 k input resistor)
 *   ST-LINK virtual COM port = USART1, PA9 TX / PB7 RX, 921600 baud 8N1
 *
 * Coexists with the sensor-node wiring (MPU6050 on D14/D15, DHT11 on D2,
 * 433 MHz TX/RX on D1/D0, PDM mic on D12/D13): those pins are left as inputs,
 * except D1 (PC6, 433 MHz transmitter data), which is held low so the
 * transmitter stays silent and cannot inject noise during a measurement.
 *
 * Serial protocol (PC -> board):
 *   'P'               -> one text line describing the configuration
 *   'C' <u16 amp LE>  -> set tone amplitude (PWM counts, 0..2100), wait 0.2 s,
 *                        capture 2^20 bits (21 s), then send one binary frame:
 *     header  "SDM1" u32 n_bits, u32 n_dec, u16 amp, u16 cic_r, u32 fs_hz, u32 dds_inc
 *     payload n_bits/8 bytes of packed bits (LSB first), n_dec int32 CIC outputs (LE)
 *     trailer u32 sum of all payload bytes (mod 2^32)
 *
 * Stored bit b = comparator output. The analog integrator is inverting, so the
 * DAC level is v = 1 - 2b and the ones-density is 1 - Vin / VDD.
 */
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "stm32f7xx.h"

/* ---- clocking -------------------------------------------------------------- */
#define SYSCLK_HZ   216000000u
#define PCLK2_HZ    108000000u
#define FS_HZ       50000u
#define TIM1_ARR    (SYSCLK_HZ / FS_HZ - 1u)   /* TIM1 clock = 2 x PCLK2 = 216 MHz -> 4319 */
#define PWM_FULL    (TIM1_ARR + 1u)            /* 4320 counts = 100 % duty               */
#define PWM_MID     (PWM_FULL / 2u)
#define AMP_MAX     2100u                      /* keeps the duty inside [60, 4260]       */

/* ---- test tone: 32-bit phase accumulator, 1024-point table + linear interp. -- */
#define DDS_INC     5239977u                   /* round(61 / 50000 * 2^32) -> 60.99999 Hz */
#define SINE_BITS   10u
#define SINE_LEN    (1u << SINE_BITS)

/* ---- capture ---------------------------------------------------------------- */
#define CIC_R       64u
#define N_BITS      (1u << 20)                 /* 20.97 s at 50 kHz */
#define N_BYTES     (N_BITS / 8u)
#define N_DEC       (N_BITS / CIC_R)
#define SETTLE_N    10000u                     /* 0.2 s after an amplitude change */
#define BAUD        921600u

#define FB_PIN      3u                         /* PI3 = Arduino D7 */
#define CMP_PIN     7u                         /* PG7 = Arduino D4 */
#define RFTX_PIN    6u                         /* PC6 = Arduino D1, 433 MHz TX data */

enum { ST_IDLE = 0, ST_SETTLE, ST_RUN, ST_DONE };

static float    sine_tab[SINE_LEN + 1u];
static uint8_t  bit_buf[N_BYTES];              /* 128 KiB */
static int32_t  dec_buf[N_DEC];                /*  64 KiB */

static volatile uint32_t state = ST_IDLE;
static volatile uint32_t settle_left;
static volatile float    amp_counts = 0.0f;    /* tone amplitude in PWM counts */

static uint32_t bit_idx, dec_idx, dphase;
static uint32_t i1, i2, i3, z1, z2, z3;        /* CIC state, wrapping 32-bit arithmetic */

/* ============================================================================ */
/*  50 kHz sample clock: latch, 1-bit DAC, tone generator, decimator            */
/* ============================================================================ */
void TIM1_UP_TIM10_IRQHandler(void)
{
    TIM1->SR = ~TIM_SR_UIF;

    /* 1) latch the comparator, 2) drive the 1-bit DAC with it.
     *    Done first so the feedback edge has a fixed delay after the clock edge. */
    uint32_t b = (GPIOG->IDR >> CMP_PIN) & 1u;
    GPIOI->BSRR = b ? (1u << FB_PIN) : (1u << (FB_PIN + 16u));

    /* 3) next PWM duty: DDS sine plus first-order error feedback, so the duty
     *    quantisation error is pushed to high frequency where the RC filter
     *    and the CIC remove it. */
    static uint32_t phase;
    static float    err;
    phase += DDS_INC;
    uint32_t k  = phase >> (32u - SINE_BITS);
    float    fr = (float)((phase >> (16u - SINE_BITS)) & 0xFFFFu) * (1.0f / 65536.0f);
    float    s  = sine_tab[k] + (sine_tab[k + 1u] - sine_tab[k]) * fr;
    float    target = (float)PWM_MID + amp_counts * s + err;
    int32_t  d = (int32_t)(target + 0.5f);
    if (d < 0) d = 0;
    if (d > (int32_t)PWM_FULL) d = (int32_t)PWM_FULL;
    err = target - (float)d;
    TIM1->CCR1 = (uint32_t)d;                  /* preloaded: applies from the next period */

    /* 4) capture raw bits and run the CIC decimator (K = 3, R = 64, M = 1) */
    uint32_t st = state;
    if (st == ST_RUN) {
        if (b) bit_buf[bit_idx >> 3] |= (uint8_t)(1u << (bit_idx & 7u));
        uint32_t x = b ? 0xFFFFFFFFu : 1u;     /* v = 1 - 2b  ->  -1 or +1 */
        i1 += x;  i2 += i1;  i3 += i2;
        if (++dphase == CIC_R) {
            dphase = 0u;
            uint32_t c1 = i3 - z1;  z1 = i3;
            uint32_t c2 = c1 - z2;  z2 = c1;
            uint32_t c3 = c2 - z3;  z3 = c2;
            dec_buf[dec_idx++] = (int32_t)c3;  /* |c3| <= 64^3, exact despite wrapping */
        }
        if (++bit_idx == N_BITS) state = ST_DONE;
    } else if (st == ST_SETTLE) {
        if (--settle_left == 0u) {
            bit_idx = dec_idx = dphase = 0u;
            i1 = i2 = i3 = z1 = z2 = z3 = 0u;
            state = ST_RUN;
        }
    }
}

/* ============================================================================ */
/*  Hardware setup (register level, CMSIS only)                                 */
/* ============================================================================ */
static void clock_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_PWREN;
    (void)RCC->APB1ENR;
    PWR->CR1 |= PWR_CR1_VOS;                              /* voltage scale 1 */

    RCC->CR |= RCC_CR_HSEON;                              /* 25 MHz crystal (X2) */
    while (!(RCC->CR & RCC_CR_HSERDY)) { }

    /* 25 MHz / 25 * 432 = 432 MHz VCO; /2 = 216 MHz SYSCLK; /9 = 48 MHz */
    RCC->PLLCFGR = 0x20000000u | RCC_PLLCFGR_PLLSRC_HSE
                 | (25u  << RCC_PLLCFGR_PLLM_Pos)
                 | (432u << RCC_PLLCFGR_PLLN_Pos)
                 | (0u   << RCC_PLLCFGR_PLLP_Pos)         /* PLLP = 2 */
                 | (9u   << RCC_PLLCFGR_PLLQ_Pos);
    RCC->CR |= RCC_CR_PLLON;

    PWR->CR1 |= PWR_CR1_ODEN;                             /* over-drive, needed > 180 MHz */
    while (!(PWR->CSR1 & PWR_CSR1_ODRDY)) { }
    PWR->CR1 |= PWR_CR1_ODSWEN;
    while (!(PWR->CSR1 & PWR_CSR1_ODSWRDY)) { }
    while (!(RCC->CR & RCC_CR_PLLRDY)) { }

    FLASH->ACR = FLASH_ACR_LATENCY_7WS | FLASH_ACR_PRFTEN | FLASH_ACR_ARTEN;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_7WS) { }

    RCC->CFGR = (RCC->CFGR & ~(RCC_CFGR_HPRE | RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2))
              | RCC_CFGR_HPRE_DIV1 | RCC_CFGR_PPRE1_DIV4 | RCC_CFGR_PPRE2_DIV2;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) { }

    SystemCoreClock = SYSCLK_HZ;
}

static void set_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode)
{
    g->MODER = (g->MODER & ~(3u << (2u * pin))) | (mode << (2u * pin));
}

static void set_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af)
{
    volatile uint32_t *r = &g->AFR[pin >> 3];
    uint32_t sh = 4u * (pin & 7u);
    *r = (*r & ~(0xFu << sh)) | (af << sh);
    set_mode(g, pin, 2u);
}

static void gpio_init(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_GPIOBEN | RCC_AHB1ENR_GPIOCEN
                  | RCC_AHB1ENR_GPIOGEN | RCC_AHB1ENR_GPIOIEN;
    (void)RCC->AHB1ENR;

    GPIOI->BSRR = 1u << (FB_PIN + 16u);                   /* FB: output, starts low */
    set_mode(GPIOI, FB_PIN, 1u);
    set_mode(GPIOG, CMP_PIN, 0u);                         /* CMP: input, no pull */
    GPIOG->PUPDR &= ~(3u << (2u * CMP_PIN));

    GPIOC->BSRR = 1u << (RFTX_PIN + 16u);                 /* 433 MHz TX data low = no carrier */
    set_mode(GPIOC, RFTX_PIN, 1u);

    set_af(GPIOA, 8u, 1u);                                /* PA8 = TIM1_CH1 */
    GPIOA->OSPEEDR = (GPIOA->OSPEEDR & ~(3u << 16)) | (1u << 16);
    set_af(GPIOA, 9u, 7u);                                /* PA9 = USART1_TX */
    set_af(GPIOB, 7u, 7u);                                /* PB7 = USART1_RX */
    GPIOB->PUPDR = (GPIOB->PUPDR & ~(3u << 14)) | (1u << 14);
}

static void uart_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;                 /* kernel clock = PCLK2 */
    (void)RCC->APB2ENR;
    USART1->BRR = (PCLK2_HZ + BAUD / 2u) / BAUD;          /* 117 -> 923 kbaud, +0.16 % */
    USART1->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
}

static void tim1_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    (void)RCC->APB2ENR;
    TIM1->PSC   = 0u;
    TIM1->ARR   = TIM1_ARR;
    TIM1->CCR1  = PWM_MID;
    TIM1->CCMR1 = (6u << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;   /* PWM mode 1, preload */
    TIM1->CCER  = TIM_CCER_CC1E;
    TIM1->BDTR  = TIM_BDTR_MOE;                           /* advanced timer: main output on */
    TIM1->CR1   = TIM_CR1_ARPE;
    TIM1->EGR   = TIM_EGR_UG;                             /* load the preloaded registers */
    TIM1->SR    = 0u;
    TIM1->DIER  = TIM_DIER_UIE;
    NVIC_SetPriority(TIM1_UP_TIM10_IRQn, 0u);
    NVIC_EnableIRQ(TIM1_UP_TIM10_IRQn);
    TIM1->CR1  |= TIM_CR1_CEN;
}

/* ============================================================================ */
/*  Serial link                                                                 */
/* ============================================================================ */
static void uart_putc(uint8_t c)
{
    while (!(USART1->ISR & USART_ISR_TXE)) { }
    USART1->TDR = c;
}

static uint32_t uart_write(const void *p, uint32_t n, uint32_t sum)
{
    const uint8_t *b = (const uint8_t *)p;
    while (n--) {
        sum += *b;
        uart_putc(*b++);
    }
    return sum;
}

static void uart_puts(const char *s)
{
    while (*s) uart_putc((uint8_t)*s++);
}

static uint8_t uart_getc(void)
{
    for (;;) {
        uint32_t isr = USART1->ISR;
        if (isr & (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE))
            USART1->ICR = USART_ICR_ORECF | USART_ICR_FECF | USART_ICR_NCF;
        if (isr & USART_ISR_RXNE)
            return (uint8_t)USART1->RDR;
    }
}

struct __attribute__((packed)) frame_header {
    char     magic[4];
    uint32_t n_bits;
    uint32_t n_dec;
    uint16_t amp;
    uint16_t cic_r;
    uint32_t fs_hz;
    uint32_t dds_inc;
};

static void capture_and_send(uint32_t amp)
{
    memset(bit_buf, 0, sizeof bit_buf);
    amp_counts  = (float)amp;
    settle_left = SETTLE_N;
    __asm volatile ("" ::: "memory");
    __DSB();
    state = ST_SETTLE;

    while (state != ST_DONE) { }
    __asm volatile ("" ::: "memory");

    struct frame_header h = {
        .magic = {'S', 'D', 'M', '1'},
        .n_bits = N_BITS, .n_dec = N_DEC, .amp = (uint16_t)amp,
        .cic_r = CIC_R, .fs_hz = FS_HZ, .dds_inc = DDS_INC,
    };
    uart_write(&h, sizeof h, 0u);
    uint32_t sum = uart_write(bit_buf, sizeof bit_buf, 0u);
    sum = uart_write(dec_buf, sizeof dec_buf, sum);
    uart_write(&sum, sizeof sum, 0u);
    state = ST_IDLE;
}

int main(void)
{
    clock_init();
    SCB_EnableICache();
    SCB_EnableDCache();                                   /* CPU-only buffers, no DMA */
    gpio_init();
    uart_init();
    for (uint32_t i = 0; i <= SINE_LEN; i++)
        sine_tab[i] = sinf(6.283185307f * (float)i / (float)SINE_LEN);
    tim1_init();                                          /* modulator loop runs from here on */

    uart_puts("\r\nSDM1 ready\r\n");
    for (;;) {
        uint8_t c = uart_getc();
        if (c == 'P') {
            uart_puts("SDM1 fs=50000 R=64 K=3 nbits=1048576 fin=61.0 pwm_full=4320 amp_max=2100\n");
        } else if (c == 'C') {
            uint32_t a = uart_getc();
            a |= (uint32_t)uart_getc() << 8;
            if (a > AMP_MAX) a = AMP_MAX;
            capture_and_send(a);
        }
    }
}
