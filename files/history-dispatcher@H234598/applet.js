const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const Settings = imports.ui.settings;
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
const MIN_REFRESH_SECONDS = 5;
const MAX_REFRESH_SECONDS = 3600;
const ALLOWED_ACTIONS = { "collect": true };

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
    this.dispatchPaused = false;
    this.dispatchBatchSize = 20;
    this.maxAttempts = 12;
    this.removed = false;
    this.generation = 0;
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
    this.settings.bindProperty(Settings.BindingDirection.IN, "dispatch-paused", "dispatchPaused", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "dispatch-batch-size", "dispatchBatchSize", null, null);
    this.settings.bindProperty(Settings.BindingDirection.IN, "max-attempts", "maxAttempts", null, null);
  },

  _safeNumber: function(value, fallback, minimum, maximum) {
    let number = Number(value);
    if (!Number.isInteger(number) || number < minimum || number > maximum) {
      return fallback;
    }
    return number;
  },

  _snapshotPath: function() {
    let runtime = String(this.runtimePath || DEFAULT_RUNTIME_PATH);
    if (!runtime || /[\u0000\u0001-\u001f\u007f]/.test(runtime) || runtime.indexOf("..") >= 0) {
      return DEFAULT_RUNTIME_PATH + "/status-v1.json";
    }
    return runtime + "/status-v1.json";
  },

  _render: function() {
    try {
      if (!this.menu) {
        return;
      }
      this.menu.removeAll();
      let payload = this.payload || {};
      this.menu.addMenuItem(this._line(payload.ok === false ? "HD: Warnung" : "HD: bereit", true));
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
      this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this.menu.addMenuItem(this._action("Status aktualisieren", () => this._refresh()));
      if (this.enableActions && ALLOWED_ACTIONS.collect) {
        this.menu.addMenuItem(this._action("Collector jetzt ausführen", () => this._runAction("collect")));
        this.menu.addMenuItem(this._action("Konfiguration anwenden", () => this._runConfigApply()));
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
      file.load_contents_async(null, (source, result) => {
        if (this.removed || generation !== this.generation) {
          return;
        }
        try {
          let loaded = source.load_contents_finish(result);
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
      this.running = false;
      this.errorText = String(error);
      this._render();
    }
  },

  _runAction: function(action) {
    if (!this.enableActions || !ALLOWED_ACTIONS[action] || this.removed) {
      return;
    }
    let generation = this.generation;
    try {
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
      let process = launcher.spawnv([this.commandPath, "--config", this.configPath, "collect"]);
      process.wait_async(null, (child, result) => {
        if (this.removed || generation !== this.generation) {
          return;
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

  _runConfigApply: function() {
    if (!this.enableActions || this.removed) {
      return;
    }
    let values = {
      collector_interval_seconds: this._safeNumber(this.collectorIntervalSeconds, 300, 60, 86400),
      dispatch_paused: Boolean(this.dispatchPaused),
      dispatch_batch_size: this._safeNumber(this.dispatchBatchSize, 20, 1, 1000),
      max_attempts: this._safeNumber(this.maxAttempts, 12, 1, 1000)
    };
    let generation = this.generation;
    try {
      let launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
      let process = launcher.spawnv([
        this.commandPath,
        "--config",
        this.configPath,
        "config-apply",
        "--values-json",
        JSON.stringify(values)
      ]);
      process.wait_async(null, (child, result) => {
        if (this.removed || generation !== this.generation) {
          return;
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
    return null;
  }
}
