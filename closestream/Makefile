# ----------------------------
# Makefile Options
# ----------------------------

NAME=closestream

# Select option for Argument Processing at 'int main( int argc, char* argv[] )'
# 0: Simple Command Line Processing
# 1: Complex Command Line Processing - for Redirection & Quoting
LDHAS_ARG_PROCESSING = 0
LDHAS_EXIT_HANDLER = 0

# ----------------------------
#
include $(shell agondev-config --makefile)

# Common network utility code
CFLAGS += -I../common
COMMON_SRC = ../common/esp8266.c
COMMON_OBJ = $(OBJDIR)/esp8266.o
OBJS += $(COMMON_OBJ)
$(LINKBINARY): $(COMMON_OBJ)

$(COMMON_OBJ): $(COMMON_SRC)
	@echo [compiling $<]
	@mkdir -p $(dir $@)
	$(V)$(CC) $(CFLAGS) -I../common $< -c -o $@
