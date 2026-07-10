const Applet = imports.ui.applet;
const ModalDialog = imports.ui.modalDialog;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const St = imports.gi.St;
const Mainloop = imports.mainloop;
const ByteArray = imports.byteArray;

const UUID = "history-dispatcher@H234598";
const DEFAULT_CONFIG_PATH = GLib.build_filenamev([GLib.get_home_dir(), ".config", "history-dispatcher", "config.toml"]);
const DEFAULT_RUNTIME_PATH = GLib.build_filenamev([GLib.getenv("XDG_RUNTIME_DIR") || GLib.build_filenamev(["/run", "user", String(0)]), "history-dispatcher"]);
const DEFAULT_COMMAND_PATH = GLib.build_filenamev([GLib.get_home_dir(), "History-Dispatcher", ".venv-py313", "bin", "history-dispatcher"]);
const MAX_SNAPSHOT_BYTES = 64 * 1024;
const MAX_LINES = 100;
const STALE_AFTER_SECONDS = 120;
const MIN_REFRESH_SECONDS = 5;
const MAX_REFRESH_SECONDS = 3600;
const ALLOWED_ACTIONS = {
  "collect": true,
  "retry": true,
  "service-start": true,
  "service-stop": true,
  "service-restart": true
};

function HistoryDispatcherApplet(metadata, orientation, panelHeight, instanceId) {
  this._init(metadata, orientation, panelHeight, instanceId);
}

HistoryDispatcherApplet.prototype = {
  __proto__: Applet.TextIconApplet.prototype,

  _init: function(metadata, orientation, panelHeight, instanceId) {
    Applet.TextIconApplet.prototype._init.call(this, orientation, panelHeight, instanceId);
    this.metadata = metadata;
    this.configPath = DEFAULT_CONFIG_PATH;
    this.runtimePath = DEFAULT_RUNTIME_PATH;
    this.commandPath = DEFAULT_COMMAND_PATH;
    this.refreshSeconds = 30;
    this.autoRefresh = true;
    this.showCollector = true;
    this.showQueue = true;
    this.showDispatch = true;
    this.maxLines = 20;
    this.enableActions = true;
    this.confirmActions = true;
    this.collectorIntervalSeconds = 300;
    this.collectorEnabled = true;
    this.collectorScanLimit = 25;
    this.logLevel = "INFO";
    this.statusHeartbeatSeconds = 30;
    this.dispatchEnabled = true;
    this.dispatchPaused = false;
    this.dispatchBatchSize = 20;
    this.claimTtlSeconds = 900;
    this.maxAttempts = 12;
    this.completedRetentionDays = 30;
    this.auditRetentionDays = 365;
    this.removed = false;
    this.generation = 0;
    this.cancellable = Gio.Cancellable ? new Gio.Cancellable() : null;
    this.timer = 0;
    this.running = false;
    this.pending = false;
    this.payload = null;
    this.errorText = "";

    this.set_applet_icon_path(this.metadata.path + "/icon.svg");
    this.set_applet_label("HD");
    this.set_applet_tooltip("History-Dispatcher");
    this.menuManager = new PopupMenu.PopupMenuManager(this);
    this.menu = new Applet.AppletPopupMenu(this, orientation);
    this.menuManager.addMenu(this.menu);
    this.settings = new Settings.AppletSettings(this, UUID, instanceId);
    this._bindSettings();
    this._render();
    this._refresh();
    this._schedule();
  },

  _bindSettings: function() {
    this.settings.bindProperty(Settings.BindingDirection.IN, "config-path", "configPath", this._onSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "runtime-path", "runtimePath", this._onSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "command-path", "commandPath", this._onSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "refresh-seconds", "refreshSeconds", this._onRefreshSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "auto-refresh", "autoRefresh", this._onRefreshSettings, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-collector", "showCollector", this._render, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-queue", "showQueue", this._render, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "show-dispatch", "showDispatch", this._render, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "max-lines", "maxLines", this._render, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "enable-actions", "enableActions", this._render, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "confirm-actions", "confirmActions", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "collector-interval-seconds", "collectorIntervalSeconds", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "collector-enabled", "collectorEnabled", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "collector-scan-limit", "collectorScanLimit", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "log-level", "logLevel", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "status-heartbeat-seconds", "statusHeartbeatSeconds", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "dispatch-enabled", "dispatchEnabled", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "dispatch-paused", "dispatchPaused", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "dispatch-batch-size", "dispatchBatchSize", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "claim-ttl-seconds", "claimTtlSeconds", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "max-attempts", "maxAttempts", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "completed-retention-days", "completedRetentionDays", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "audit-retention-days", "auditRetentionDays", null, null);
  },

  _safeNumber: function(value, fallback, minimum, maximum) {
    let number = Number(value);
    if (!Number.isInteger(number) || number < minimum || number > maximum) {
      return fallback;
    }
    return number;
  },

  _isStale: function(payload) {
    let generated = Date.parse(String((payload || {}).generated_at || ""));
    return !Number.isFinite(generated) || (Date.now() - generated) > STALE_AFTER_SECONDS * 1000;
  },

  _snapshotPath: function() {
    return this._safeLocalPath(this.runtimePath, DEFAULT_RUNTIME_PATH) + "/status-v1.json";
  },

  _safeLocalPath: function(value, fallback) {
    let defaultPath = String(fallback || DEFAULT_RUNTIME_PATH);
    let path = String(value || defaultPath).trim();
    if (!path || path.charAt(0) !== "/" || path.length > 4096 || /[\u0000-\u001f\u007f]/.test(path) || path.indexOf("..") >= 0 || /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(path)) {
      return defaultPath;
    }
    return path;
  },

  _safeCommandPath: function() {
    let path = String(this.commandPath || DEFAULT_COMMAND_PATH).trim();
    if (path !== DEFAULT_COMMAND_PATH && !/^\/(?:usr\/bin|usr\/local\/bin|bin)\/[A-Za-z0-9._+-]+$/.test(path)) {
      return DEFAULT_COMMAND_PATH;
    }
    return path;
  },

  _safeConfigPath: function() {
    return this._safeLocalPath(this.configPath, DEFAULT_CONFIG_PATH);
  },

  _render: function() {
    try {
      if (!this.menu) {
        return;
      }
      this.menu.removeAll();
      let payload = this.payload || {};
      let stale = this._isStale(payload);
      this.menu.addMenuItem(this._line(payload.ok === false ? "HD: Warnung" : (stale ? "HD: veraltet" : "HD: bereit"), true));
      if (this.errorText) {
        this.menu.addMenuItem(this._line(this._short(this.errorText, 180), false));
      }
      let lines = [];
      if (this.showQueue) {
        lines.push("Queue: " + String(payload.queued || 0) + " / gesamt " + String(payload.total || 0));
        if (payload.oldest_queued_at) {
          lines.push("Ältester Eintrag: " + String(payload.oldest_queued_at));
        }
      }
      if (this.showCollector && payload.collector) {
        lines.push("Collector: " + (payload.collector.enabled ? "aktiv" : "aus") + " / Sources " + String(payload.collector.sources || 0));
      }
      if (this.showDispatch && payload.dispatch) {
        lines.push("Dispatch: " + (payload.dispatch.paused ? "pausiert" : (payload.dispatch.enabled ? "aktiv" : "aus")));
      }
      lines.push("Version: " + String(payload.version || "unbekannt"));
      let limit = this._safeNumber(this.maxLines, 20, 5, MAX_LINES);
      for (let i = 0; i < lines.length && i < limit; i++) {
        this.menu.addMenuItem(this._line(this._short(lines[i], 220), false));
      }
      let preview = Array.isArray(payload.queue_preview) ? payload.queue_preview : [];
      for (let i = 0; i < preview.length && i < 10; i++) {
        let item = preview[i] || {};
        let itemId = String(item.id || "");
        if (!itemId) {
          continue;
        }
        let state = String(item.status || "unknown");
        this.menu.addMenuItem(this._line("Eintrag " + this._short(itemId, 24) + ": " + state, false));
        if (this.enableActions && state === "failed") {
          this.menu.addMenuItem(this._action("Retry " + this._short(itemId, 20), () => this._runAction("retry", itemId)));
        }
        if (this.enableActions) {
          this.menu.addMenuItem(this._action("Löschen " + this._short(itemId, 20), () => this._confirmDelete(itemId)));
        }
      }
      this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this.menu.addMenuItem(this._action("Status aktualisieren", () => this._refresh()));
      if (this.enableActions && ALLOWED_ACTIONS.collect) {
        this.menu.addMenuItem(this._action("Collector jetzt ausführen", () => this._runAction("collect")));
        this.menu.addMenuItem(this._action("Konfiguration anwenden", () => this._runConfigApply()));
        this.menu.addMenuItem(this._action("Dienst starten", () => this._runAction("service-start")));
        this.menu.addMenuItem(this._action("Dienst neu starten", () => this._runAction("service-restart")));
        this.menu.addMenuItem(this._action("Dienst stoppen", () => this._runAction("service-stop")));
      }
    } catch (error) {
      this._log(error);
    }
  },

  _line: function(text, bold) {
    let item = new PopupMenu.PopupMenuItem(String(text || ""));
    if (bold && item.label && item.label.set_style) {
      item.label.set_style("font-weight: bold; max-width: 42em;");
    }
    return item;
  },

  _action: function(text, callback) {
    let item = new PopupMenu.PopupMenuItem(text);
    item.connect("activate", () => {
      try {
        callback();
      } catch (error) {
        this._log(error);
      }
    });
    return item;
  },

  _refresh: function() {
    if (this.removed) {
      return;
    }
    if (this.running) {
      this.pending = true;
      return;
    }
    this.running = true;
    let generation = this.generation;
    let file = Gio.file_new_for_path(this._snapshotPath());
    try {
      file.query_info_async("standard::size", Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT, this.cancellable, (source, result) => {
        if (this.removed || generation !== this.generation) {
          return;
        }
        try {
          let info = source.query_info_finish(result);
          if (info.get_size() > MAX_SNAPSHOT_BYTES) {
            throw new Error("Status-Snapshot zu groß");
          }
          source.load_contents_async(this.cancellable, (loadedSource, loadedResult) => {
            if (this.removed || generation !== this.generation) {
              return;
            }
            try {
              let loaded = loadedSource.load_contents_finish(loadedResult);
              let text = ByteArray.toString(loaded[1]);
              if (text.length > MAX_SNAPSHOT_BYTES) {
                throw new Error("Status-Snapshot zu groß");
              }
              let payload = JSON.parse(text);
              if (!payload || typeof payload !== "object" || payload.schema_version !== 1) {
                throw new Error("Ungültiger Status-Snapshot");
              }
              this.payload = payload;
              this.errorText = "";
            } catch (error) {
              this.errorText = String(error);
            }
            this.running = false;
            this._render();
            if (this.pending && !this.removed) {
              this.pending = false;
              this._refresh();
            }
          });
        } catch (error) {
          this.errorText = String(error);
          this.running = false;
          this._render();
        }
      });
    } catch (error) {
      this.running = false;
      this.errorText = String(error);
      this._render();
    }
  },

  _runAction: function(action, itemId) {
    if (!this.enableActions || !ALLOWED_ACTIONS[action] || this.removed) {
      return;
    }
    let generation = this.generation;
    let args = [this._safeCommandPath(), "--config", this._safeConfigPath()];
    args.push("applet-action", "--action", action);
    if (action === "retry") {
      args.push("--item-id", String(itemId || ""));
    }
    try {
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
      let process = launcher.spawnv(args);
      let done = false;
      let timeout = Mainloop.timeout_add(30000, () => {
        if (done) {
          return false;
        }
        done = true;
        try {
          if (!process.get_if_exited()) {
            process.force_exit();
          }
        } catch (error) {
          this._log(error);
        }
        if (!this.removed && generation === this.generation) {
          this.errorText = "Aktion Timeout";
          this._render();
        }
        return false;
      });
      process.wait_async(null, (child, result) => {
        if (done || this.removed || generation !== this.generation) {
          return;
        }
        done = true;
        if (timeout) {
          Mainloop.source_remove(timeout);
        }
        try {
          child.wait_finish(result);
          this.errorText = child.get_successful() ? "" : "Aktion fehlgeschlagen";
        } catch (error) {
          this.errorText = String(error);
        }
        this._refresh();
      });
    } catch (error) {
      this.errorText = String(error);
      this._render();
    }
  },

  _confirmDelete: function(itemId) {
    if (!this.enableActions || this.removed || !String(itemId || "")) {
      return;
    }
    let dialog = new ModalDialog.ModalDialog();
    let completed = false;
    let finish = (confirmed) => {
      if (completed) {
        return;
      }
      completed = true;
      if (confirmed) {
        this._runDelete(itemId);
      }
    };
    try {
      dialog.contentLayout.add_child(new St.Label({
        text: "Queue-Eintrag endgültig löschen?",
        x_expand: true
      }));
      dialog.contentLayout.add_child(new St.Label({
        text: String(itemId).slice(0, 96) + " / LOESCHEN 1",
        x_expand: true
      }));
      dialog.setButtons([
        {
          label: "Abbrechen",
          key: Clutter.KEY_Escape,
          action: function() {
            dialog.close();
            finish(false);
          }
        },
        {
          label: "LOESCHEN 1",
          action: function() {
            dialog.close();
            finish(true);
          }
        }
      ]);
      if (!dialog.open()) {
        this.errorText = "Bestätigungsdialog konnte nicht geöffnet werden";
        finish(false);
      }
    } catch (error) {
      this._log(error);
      finish(false);
    }
  },

  _runDelete: function(itemId) {
    let generation = this.generation;
    try {
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
      let process = launcher.spawnv([
        this._safeCommandPath(),
        "--config",
        this._safeConfigPath(),
        "delete-item",
        "--item-id",
        String(itemId)
      ]);
      let done = false;
      let timeout = Mainloop.timeout_add(30000, () => {
        if (done) {
          return false;
        }
        done = true;
        try {
          if (!process.get_if_exited()) {
            process.force_exit();
          }
        } catch (error) {
          this._log(error);
        }
        if (!this.removed && generation === this.generation) {
          this.errorText = "Löschen Timeout";
          this._render();
        }
        return false;
      });
      process.wait_async(null, (child, result) => {
        if (done || this.removed || generation !== this.generation) {
          return;
        }
        done = true;
        if (timeout) {
          Mainloop.source_remove(timeout);
        }
        try {
          child.wait_finish(result);
          this.errorText = child.get_successful() ? "" : "Löschen fehlgeschlagen";
        } catch (error) {
          this.errorText = String(error);
        }
        this._refresh();
      });
    } catch (error) {
      this.errorText = String(error);
      this._render();
    }
  },

  _runConfigApply: function() {
    if (!this.enableActions || this.removed) {
      return;
    }
    let values = {
      collector_enabled: Boolean(this.collectorEnabled),
      collector_interval_seconds: this._safeNumber(this.collectorIntervalSeconds, 300, 60, 86400),
      collector_scan_limit: this._safeNumber(this.collectorScanLimit, 25, 1, 10000),
      log_level: ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].indexOf(String(this.logLevel || "INFO").toUpperCase()) >= 0 ? String(this.logLevel || "INFO").toUpperCase() : "INFO",
      status_heartbeat_seconds: this._safeNumber(this.statusHeartbeatSeconds, 30, 1, 3600),
      dispatch_enabled: Boolean(this.dispatchEnabled),
      dispatch_paused: Boolean(this.dispatchPaused),
      dispatch_batch_size: this._safeNumber(this.dispatchBatchSize, 20, 1, 1000),
      claim_ttl_seconds: this._safeNumber(this.claimTtlSeconds, 900, 1, 604800),
      max_attempts: this._safeNumber(this.maxAttempts, 12, 1, 1000),
      completed_retention_days: this._safeNumber(this.completedRetentionDays, 30, 1, 3650),
      audit_retention_days: this._safeNumber(this.auditRetentionDays, 365, 1, 3650)
    };
    let generation = this.generation;
    try {
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
      let process = launcher.spawnv([
        this._safeCommandPath(),
        "--config",
        this._safeConfigPath(),
        "config-apply",
        "--values-json",
        JSON.stringify(values)
      ]);
      let done = false;
      let timeout = Mainloop.timeout_add(30000, () => {
        if (done) {
          return false;
        }
        done = true;
        try {
          if (!process.get_if_exited()) {
            process.force_exit();
          }
        } catch (error) {
          this._log(error);
        }
        if (!this.removed && generation === this.generation) {
          this.errorText = "Konfiguration Timeout";
          this._render();
        }
        return false;
      });
      process.wait_async(null, (child, result) => {
        if (done || this.removed || generation !== this.generation) {
          return;
        }
        done = true;
        if (timeout) {
          Mainloop.source_remove(timeout);
        }
        try {
          child.wait_finish(result);
          this.errorText = child.get_successful() ? "" : "Konfiguration konnte nicht angewendet werden";
        } catch (error) {
          this.errorText = String(error);
        }
        this._refresh();
      });
    } catch (error) {
      this.errorText = String(error);
      this._render();
    }
  },

  _schedule: function() {
    if (this.timer) {
      Mainloop.source_remove(this.timer);
      this.timer = 0;
    }
    if (!this.autoRefresh || this.removed) {
      return;
    }
    let seconds = this._safeNumber(this.refreshSeconds, 30, MIN_REFRESH_SECONDS, MAX_REFRESH_SECONDS);
    this.timer = Mainloop.timeout_add_seconds(seconds, () => {
      try {
        this._refresh();
      } catch (error) {
        this._log(error);
      }
      return !this.removed && Boolean(this.autoRefresh);
    });
  },

  _onSettings: function() {
    this._refresh();
    this._render();
  },

  _onRefreshSettings: function() {
    this._schedule();
    this._refresh();
  },

  _short: function(value, limit) {
    let text = String(value || "").replace(/\s+/g, " ");
    return text.length <= limit ? text : text.slice(0, limit - 1) + "…";
  },

  _log: function(error) {
    try {
      global.logError(error);
    } catch (_) {
      // Cinnamon may already be shutting down.
    }
  },

  on_applet_clicked: function() {
    try {
      this._refresh();
      this.menu.toggle();
    } catch (error) {
      this._log(error);
    }
  },

  on_applet_removed_from_panel: function() {
    this.removed = true;
    this.generation += 1;
    try {
      if (this.cancellable) this.cancellable.cancel();
    } catch (error) {
      this._log(error);
    }
    if (this.timer) {
      Mainloop.source_remove(this.timer);
      this.timer = 0;
    }
    if (this.menu) {
      this.menu.destroy();
      this.menu = null;
    }
  }
};

function main(metadata, orientation, panelHeight, instanceId) {
  try {
    return new HistoryDispatcherApplet(metadata, orientation, panelHeight, instanceId);
  } catch (error) {
    try {
      global.logError(error);
    } catch (_) {}
    let fallback = Object.create(Applet.TextIconApplet.prototype);
    try {
      Applet.TextIconApplet.prototype._init.call(fallback, orientation, panelHeight, instanceId);
      fallback.set_applet_label("HD!");
      fallback.set_applet_tooltip("History-Dispatcher konnte nicht initialisiert werden");
    } catch (_) {}
    return fallback;
  }
}
