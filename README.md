# AI Font Assistant - Glyphs 3 Plugin

**A Glyphs 3 plugin that extends a base set of glyphs into a complete font using AI.**

Developed by Eric Lu / [Mixfont](https://www.mixfont.com).

![AI Font Assistant demo](https://static.mixfont.com/assets/20260615-224346-glyphs1_2_v1-6xm66uw8.webp)

---

## Overview

The AI Font Assistant plugin for Glyphs 3 generates a complete typeface from a few drawn letter glyphs. It uses any glyphs in your current project as a style reference, and will create a complete set of Latin glyphs that match the style of your base typeface. The generated font is returned as a new Glyphs document, so your original file remains unchanged.

There are two generation options: a standard generation that creates 72 basic English letters, numbers, and punctuation, or an extended generation that creates 320+ glyphs to support the full set of characters as defined in the Google Fonts [Latin core set](https://github.com/googlefonts/glyphsets/blob/main/Lib/glyphsets/definitions/GF_Latin_Core.yaml).

The generations are powered by the [Mixfont](https://www.mixfont.com) AI font generation model. Inputs are not used for AI training, but an internet connection and Mixfont credits are required to use the plugin. Users can start generating for free.

## Screenshots and Examples

[![Watch the AI Font Assistant demo](https://static.mixfont.com/assets/20260615-222542-glyphs_v1-15ff5wer.webp)](https://static.mixfont.com/assets/20260615-222319-glyphs-qhlqong5.mp4)

[Watch the demo video](https://static.mixfont.com/assets/20260615-222319-glyphs-qhlqong5.mp4)

![AI Font Assistant window in Glyphs 3](https://static.mixfont.com/assets/20260615-214416-image_v1-1-84nuiheu.webp)

![AI Font Assistant plugin in Glyphs 3](https://static.mixfont.com/assets/20260615-221628-image_v2-7lms1af5.webp)

![AI Font Assistant generate controls](https://static.mixfont.com/assets/20260615-213835-glyphs1_v1-1-m1uk134d.webp)

## Requirements

- Glyphs 3
- The Vanilla module, installed from _Window > Plugin Manager > Modules_
- A Mixfont account and internet connection

## Installation

1. Double-click `AI Font Assistant.glyphsPlugin`.
2. Restart Glyphs.
3. Open the plugin from _Glyph > AI Font Assistant..._

## Usage

1. Open a Glyphs file with a few drawn letter glyphs.
2. Choose _Glyph > AI Font Assistant..._
3. Click **Connect Mixfont Account** and sign in in the browser.
4. Return to Glyphs and click **Generate Font**.

When generation finishes, the result opens as a separate Glyphs document. Save
it as a `.glyphs` file if you want to keep editing it.

## License

MIT License — © 2026 Mixfont / Eric Lu

See [LICENSE](LICENSE) for full terms.

## About

Mixfont is frontier research lab dedicated to making font creation easier and more accessible for everyone.

Website: [mixfont.com](https://www.mixfont.com)
