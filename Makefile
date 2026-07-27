PREFIX ?= $(HOME)/.local
LIB_DIR = $(DESTDIR)$(PREFIX)/share/d4-launcher
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
	cp -r src/d4l $(LIB_DIR)/
	find $(LIB_DIR) -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	printf '#!/usr/bin/env bash\nexport PYTHONPATH="%s$${PYTHONPATH:+:$$PYTHONPATH}"\nexec python3 -m d4l "$$@"\n' \
		"$(PREFIX)/share/d4-launcher" > $(BIN_DIR)/d4l
	chmod +x $(BIN_DIR)/d4l
	install -m644 share/icons/hicolor/scalable/apps/d4-launcher.svg $(ICON_DIR)/
	for e in d4-launcher diablo-iv; do \
		sed "s|@BIN@|$(PREFIX)/bin/d4l|g" share/applications/$$e.desktop \
			> $(APPS_DIR)/$$e.desktop; \
	done
	-update-desktop-database -q $(APPS_DIR)

uninstall:
	rm -rf $(LIB_DIR)
	rm -f $(BIN_DIR)/d4l $(ICON_DIR)/d4-launcher.svg \
		$(APPS_DIR)/d4-launcher.desktop $(APPS_DIR)/diablo-iv.desktop
	-update-desktop-database -q $(APPS_DIR)

check:
	python3 -m compileall -q src/d4l
	PYTHONPATH=src python3 -m d4l --help > /dev/null
	PYTHONPATH=src python3 -m d4l status
	@echo "ok"
