PREFIX ?= $(HOME)/.local
LIB_DIR = $(DESTDIR)$(PREFIX)/share/battlenet-launcher4linux
BIN_DIR = $(DESTDIR)$(PREFIX)/bin
APPS_DIR = $(DESTDIR)$(PREFIX)/share/applications
ICON_DIR = $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps

.PHONY: install uninstall check help

help:
	@echo "make install    install to \$$PREFIX (default $(PREFIX))"
	@echo "make uninstall  remove it again"
	@echo "make check      byte-compile and smoke-test the CLI"
	@echo
	@echo "For a guided first-time setup use ./install.sh instead."

install:
	install -d $(LIB_DIR) $(BIN_DIR) $(APPS_DIR) $(ICON_DIR)
	cp -r src/bnl4l $(LIB_DIR)/
	find $(LIB_DIR) -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	printf '#!/usr/bin/env bash\nexport PYTHONPATH="%s$${PYTHONPATH:+:$$PYTHONPATH}"\nexec python3 -m bnl4l "$$@"\n' \
		"$(PREFIX)/share/battlenet-launcher4linux" > $(BIN_DIR)/bnl
	chmod +x $(BIN_DIR)/bnl
	install -m644 share/icons/hicolor/scalable/apps/battlenet-launcher4linux.svg $(ICON_DIR)/
	for e in battlenet-launcher4linux diablo-iv; do \
		X share/applications/$$e.desktop \
			> $(APPS_DIR)/$$e.desktop; \
	done
	-update-desktop-database -q $(APPS_DIR)

uninstall:
	rm -rf $(LIB_DIR)
	rm -f $(BIN_DIR)/bnl $(ICON_DIR)/battlenet-launcher4linux.svg \
		$(APPS_DIR)/battlenet-launcher4linux.desktop $(APPS_DIR)/diablo-iv.desktop
	-update-desktop-database -q $(APPS_DIR)

check:
	python3 -m compileall -q src/bnl4l
	PYTHONPATH=src python3 -m bnl4l --help > /dev/null
	PYTHONPATH=src python3 -m bnl4l status
	@echo "ok"
