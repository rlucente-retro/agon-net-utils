# Agon Family Network Utilities Makefile
# Builds openstream.bin and closestream.bin from unified src/

AGONDEV_TOOLCHAIN ?= $(shell agondev-config --prefix)

TOOLBINDIR   = $(AGONDEV_TOOLCHAIN)/bin
INCLUDEDIR   = $(AGONDEV_TOOLCHAIN)/include
LINKERCONFIG = $(AGONDEV_TOOLCHAIN)/config/linker.conf
LIBDIR       = $(AGONDEV_TOOLCHAIN)/lib

ARCH   = ez80+full
TARGET = ez80-none-elf

CC          = $(TOOLBINDIR)/ez80-none-elf-clang
CFLAGS      = -mllvm -z80-gas-style -mllvm -z80-print-zero-offset -nostdinc -Isrc -isystem $(INCLUDEDIR) -target $(TARGET) -DAGONDEV -Oz -Wa,-march=$(ARCH) -fno-threadsafe-statics -fcolor-diagnostics
LINKER      = $(TOOLBINDIR)/ez80-none-elf-ld
SETPROGNAME = $(TOOLBINDIR)/agondev-setname

RAM_START ?= 0x40000
RAM_SIZE  ?= 0x70000
MEMCONFIG = -defsym=RAM_START=$(RAM_START) -defsym=RAM_SIZE=$(RAM_SIZE) -defsym=_has_exit_handler=0
LINKERLIBFLAGS = -L$(LIBDIR) -l agon

SRCDIR = src
OBJDIR = obj
BINDIR = bin

PROGRAMS = openstream closestream
BINARIES = $(patsubst %, $(BINDIR)/%.bin, $(PROGRAMS))

V ?= @

all: $(BINDIR) $(OBJDIR) $(BINARIES)
	@echo [Done]

openstream: $(BINDIR)/openstream.bin
closestream: $(BINDIR)/closestream.bin

$(BINDIR)/%.bin: $(BINDIR)/%.noname.bin
	@echo [Start address $(RAM_START)]
	@echo [Setting name '$*.bin' in binary]
	@cp $< $@
	$(V)$(SETPROGNAME) $@ >/dev/null

$(BINDIR)/%.noname.bin: $(OBJDIR)/%.o $(OBJDIR)/esp8266.o | $(BINDIR)
	@echo [Linking $@]
	$(V)$(LINKER) $(MEMCONFIG) -Map=$(BINDIR)/$*.map -T $(LINKERCONFIG) --oformat binary -o $@ $^ $(LINKERLIBFLAGS)

$(OBJDIR)/%.o: $(SRCDIR)/%.c | $(OBJDIR)
	@echo [compiling $<]
	$(V)$(CC) $(CFLAGS) $< -c -o $@

$(BINDIR):
	@mkdir -p $(BINDIR)

$(OBJDIR):
	@mkdir -p $(OBJDIR)

clean:
	@$(RM) -r $(BINDIR) $(OBJDIR)

.PRECIOUS: $(OBJDIR)/%.o $(BINDIR)/%.noname.bin
.PHONY: all clean openstream closestream
