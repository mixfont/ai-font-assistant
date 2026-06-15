# AI Font Assistant by Mixfont — Glyphs 3 Plugin

Generates a typeface from the current Glyphs font, right inside
[Glyphs 3](https://glyphsapp.com). The plugin looks at the open font,
collects a capped set of drawn letter glyphs in the current master, renders
those available letters into a spaced lettersheet image, submits it to
Mixfont, then opens the returned TTF as a new Glyphs document.

The plugin signs in with a Mixfont account in the browser. Generations spend
the team plan's web credits.

## Screenshots

![AI Font Assistant plugin in Glyphs 3](https://static.mixfont.com/assets/20260615-212115-glyphs-screenshot-6d4wmkem.webp)

![AI Font Assistant generate controls](https://static.mixfont.com/assets/20260615-213835-glyphs1_v1-1-m1uk134d.webp)

![AI Font Assistant window in Glyphs 3](https://static.mixfont.com/assets/20260615-214416-image_v1-1-84nuiheu.webp)

## How it works

1. **Connect account**: the plugin opens Mixfont sign-in in the browser and
   stores the returned connection locally in Glyphs. Disconnect revokes the
   connection.
2. **Lettersheet**: the plugin scans the current font for letter glyphs whose
   current-master layer has a non-empty `completeBezierPath`. It uses at most
   24 letters, preferring style-bearing uppercase and lowercase forms first,
   then filling with remaining available letters. The outlines are rendered
   black-on-white in rows, using each layer's real advance width and scaled so
   ascender→descender maps to 256 px. A debug copy of the exact image
   submitted is written to the temp folder (path is printed in *Window >
   Macro Panel*). When no drawn letters are found, the plugin asks the user
   to add a few sample letters first.
3. **Generate**: the plugin posts `multipart/form-data` to Mixfont with the
   reference image. The server always creates a standard glyph-set job through
   web credit billing. The plugin waits for the job to finish, then downloads
   the generated font.
4. **Result**: the generated TTF opens as a separate Glyphs document. The
   family name is set from Mixfont's response. The original project is
   untouched, and the designer saves the result as a `.glyphs` file when they
   want to keep editing it.

## Install

1. Make sure the **Vanilla** module is installed: *Window > Plugin Manager >
   Modules*.
2. Double-click `AI Font Assistant.glyphsPlugin` (Glyphs copies it to
   `~/Library/Application Support/Glyphs 3/Plugins/`) and restart Glyphs.
3. The command appears as **Glyph > AI Font Assistant…**

## Use

1. Draw any available letter glyphs in the current font. No selection is
   required.
2. Choose *Glyph > AI Font Assistant…*.
3. Click **Connect Mixfont Account**, approve in the browser, and come back.
4. Press **Generate Font**. The result opens as a new font when it finishes.

## Development notes

- Point the plugin at a local or dev server from the Macro Panel:

  ```python
  Glyphs.defaults["com.mixfont.glyphs.apiBaseUrl"] = "http://localhost:3000"
  ```

  Set it to `None` to return to `https://www.mixfont.com`. The stored token
  lives in `Glyphs.defaults["com.mixfont.glyphs.pluginToken"]`.

- The bundle follows the official GlyphsSDK *General Plugin* template:
  `Contents/MacOS/plugin` is the SDK's prebuilt universal loader stub,
  `Contents/Resources/plugin.py` is all of the plugin code
  (`NSPrincipalClass` = `MixfontPlugin`). After editing `plugin.py`, restart
  Glyphs to reload.

## Distributing through the Plugin Manager

The best public distribution path is Glyphs' built-in Plugin Manager. Keep a
small public GitHub repo under the Mixfont org that contains this bundle at
the repo root, then submit that repo to the Glyphs package index.

1. Publish `AI Font Assistant.glyphsPlugin` at the top level of the public
   repo: `https://github.com/mixfont/ai-font-assistant`.
2. Include a short `README.md`, a license file, and one or two screenshots in
   the public repo. Do not include `__pycache__`, local build products, tokens,
   or app/server source code.
3. Make sure the production API is deployed before review. Plugin Manager
   users will hit `https://www.mixfont.com` by default.
4. Open a PR against the `glyphs3` branch of
   [`schriftgestalt/glyphs-packages`](https://github.com/schriftgestalt/glyphs-packages)
   adding an entry to `packages.plist`:

   ```
   {
       titles = { en = "AI Font Assistant"; };
       url = "https://github.com/mixfont/ai-font-assistant";
       path = "AI Font Assistant.glyphsPlugin";
       descriptions = { en = "*Glyph > AI Font Assistant* uses Mixfont AI to generate a full font from the glyphs present in the current project."; };
       dependencies = (vanilla);
       identifier = "mixfont-ai-font-assistant";
       minGlyphsVersion = "3.0";
       screenshot = "https://static.mixfont.com/assets/20260615-212115-glyphs-screenshot-6d4wmkem.webp";
   },
   ```

   After editing `packages.plist`, run `Parse Packages.command` from the
   `glyphs-packages` repo before opening the PR.

## Troubleshooting

- **"…needs the Vanilla module"** — install Vanilla via *Window > Plugin
  Manager > Modules* and restart.
- **"Your Mixfont connection expired"** — reconnect with **Connect Mixfont
  Account**.
- **"…does not have enough web credits" (402)** — visit billing to add credits
  or upgrade the team plan.
- **Anything else** — *Window > Macro Panel* shows the plugin's log,
  including the path of the reference image that was submitted.
