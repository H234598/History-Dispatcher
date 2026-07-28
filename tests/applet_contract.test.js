"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const APPLET_PATH = path.join(
  __dirname,
  "..",
  "files",
  "history-dispatcher@H234598",
  "applet.js"
);

function loadApplet() {
  const spawns = [];
  const removedSources = [];
  let nextSourceId = 1;

  function TextIconApplet() {}
  TextIconApplet.prototype._init = function () {};
  TextIconApplet.prototype.set_applet_icon_path = function () {};
  TextIconApplet.prototype.set_applet_label = function () {};
  TextIconApplet.prototype.set_applet_tooltip = function () {};

  const Gio = {
    Cancellable: class {
      constructor() {
        this.cancelled = false;
      }
      cancel() {
        this.cancelled = true;
      }
    },
    SubprocessFlags: {
      STDOUT_SILENCE: 1,
      STDERR_SILENCE: 2,
    },
    SubprocessLauncher: {
      new() {
        return {
          spawnv(argv) {
            const process = {
              argv: Array.from(argv),
              forced: false,
              get_if_exited() {
                return false;
              },
              force_exit() {
                this.forced = true;
              },
              wait_async() {},
            };
            spawns.push(process);
            return process;
          },
        };
      },
    },
    file_new_for_path() {
      throw new Error("file reads are not used by these action-contract tests");
    },
  };

  const Mainloop = {
    timeout_add() {
      return nextSourceId++;
    },
    timeout_add_seconds() {
      return nextSourceId++;
    },
    source_remove(id) {
      removedSources.push(id);
    },
  };

  const sandbox = {
    console,
    imports: {
      ui: {
        applet: { TextIconApplet },
        modalDialog: { ModalDialog: function () {} },
        popupMenu: {
          PopupMenuManager: function () {},
          AppletPopupMenu: function () {},
          PopupMenuItem: function () {},
          PopupSeparatorMenuItem: function () {},
        },
        settings: {
          AppletSettings: function () {},
          BindingDirection: { IN: 1 },
        },
      },
      gi: {
        Clutter: { KEY_Escape: 27 },
        Gio,
        GLib: {
          PRIORITY_DEFAULT: 0,
          build_filenamev(parts) {
            return path.posix.join(...parts);
          },
          get_home_dir() {
            return "/home/test";
          },
          getenv(name) {
            return name === "XDG_RUNTIME_DIR" ? "/run/user/1000" : null;
          },
        },
        St: { Label: function () {} },
      },
      mainloop: Mainloop,
      byteArray: {
        toString(value) {
          return String(value);
        },
      },
    },
    global: { logError() {} },
  };
  vm.createContext(sandbox);
  const source = fs.readFileSync(APPLET_PATH, "utf8");
  vm.runInContext(
    `${source}\n;globalThis.__testExports = { HistoryDispatcherApplet, ALLOWED_ACTIONS };`,
    sandbox,
    { filename: APPLET_PATH }
  );
  return {
    ...sandbox.__testExports,
    spawns,
    removedSources,
  };
}

function actionInstance(HistoryDispatcherApplet) {
  const instance = Object.create(HistoryDispatcherApplet.prototype);
  instance.enableActions = true;
  instance.removed = false;
  instance.generation = 4;
  instance.commandPath = "/home/test/History-Dispatcher/.venv-py313/bin/history-dispatcher";
  instance.configPath = "/home/test/.config/history-dispatcher/config.toml";
  instance.errorText = "";
  instance._render = function () {};
  instance._refresh = function () {};
  instance._log = function () {};
  return instance;
}

test("applet actions are allowlisted and use a fixed argv entrypoint", () => {
  const { HistoryDispatcherApplet, ALLOWED_ACTIONS, spawns } = loadApplet();
  const instance = actionInstance(HistoryDispatcherApplet);

  instance._runAction("arbitrary-command");
  assert.equal(spawns.length, 0);

  instance._runAction("collect");
  assert.equal(spawns.length, 1);
  assert.deepEqual(spawns[0].argv, [
    "/home/test/History-Dispatcher/.venv-py313/bin/history-dispatcher",
    "--config",
    "/home/test/.config/history-dispatcher/config.toml",
    "applet-action",
    "--action",
    "collect",
  ]);

  instance._runAction("retry", "event-1");
  assert.deepEqual(spawns[1].argv.slice(-4), [
    "--action",
    "retry",
    "--item-id",
    "event-1",
  ]);
  assert.deepEqual(Object.keys(ALLOWED_ACTIONS).sort(), [
    "collect",
    "retry",
    "service-restart",
    "service-start",
    "service-stop",
  ]);
});

test("applet removal cancels only local resources and never spawns a backend action", () => {
  const { HistoryDispatcherApplet, spawns, removedSources } = loadApplet();
  const instance = Object.create(HistoryDispatcherApplet.prototype);
  let cancelled = 0;
  let destroyed = 0;
  instance.removed = false;
  instance.generation = 7;
  instance.cancellable = {
    cancel() {
      cancelled += 1;
    },
  };
  instance.timer = 23;
  instance.menu = {
    destroy() {
      destroyed += 1;
    },
  };
  instance._log = function () {};

  instance.on_applet_removed_from_panel();

  assert.equal(instance.removed, true);
  assert.equal(instance.generation, 8);
  assert.equal(cancelled, 1);
  assert.deepEqual(removedSources, [23]);
  assert.equal(instance.timer, 0);
  assert.equal(destroyed, 1);
  assert.equal(instance.menu, null);
  assert.equal(spawns.length, 0);
});
