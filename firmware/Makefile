# sdm_f746 - bare-metal (CMSIS only) build for the STM32F746G-DISCO
# Toolchain: arm-none-eabi-gcc (bundled with STM32CubeIDE). On Windows, run build.ps1,
# which puts the CubeIDE toolchain and make on PATH and then calls this Makefile.

TARGET  = sdm_f746
BUILD   = build
PREFIX ?= arm-none-eabi-
CC      = $(PREFIX)gcc
OBJCOPY = $(PREFIX)objcopy
SIZE    = $(PREFIX)size

MCU     = -mcpu=cortex-m7 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard
DEFS    = -DSTM32F746xx
INCS    = -Icmsis/include -Icmsis/device
CFLAGS  = $(MCU) $(DEFS) $(INCS) -std=c11 -O2 -g3 -Wall -Wextra \
          -ffunction-sections -fdata-sections -fsingle-precision-constant
LDFLAGS = $(MCU) -T STM32F746NGHx_FLASH.ld --specs=nano.specs --specs=nosys.specs \
          -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map -Wl,--print-memory-usage \
          -Wl,--no-warn-rwx-segments

SRCS_C  = src/main.c src/syscalls.c cmsis/device/system_stm32f7xx.c
SRCS_S  = cmsis/device/startup_stm32f746xx.s
OBJS    = $(addprefix $(BUILD)/,$(notdir $(SRCS_C:.c=.o) $(SRCS_S:.s=.o)))

vpath %.c src cmsis/device
vpath %.s cmsis/device

all: $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%.o: %.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/%.o: %.s | $(BUILD)
	$(CC) $(MCU) -x assembler-with-cpp -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS)
	$(CC) $(OBJS) $(LDFLAGS) -lm -o $@
	$(SIZE) $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -rf $(BUILD)

.PHONY: all clean
