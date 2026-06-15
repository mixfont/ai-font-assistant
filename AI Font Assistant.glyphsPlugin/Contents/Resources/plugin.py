# encoding: utf-8

###########################################################################################################
#
# AI Font Assistant by Mixfont — Glyphs plugin
#
# Mixfont generates a typeface from drawn letters in the current font. The
# plugin writes a capped representative lettersheet image, submits it to the
# Mixfont font generation service, then opens the generated TTF as a new
# Glyphs document.
#
# Authentication: the plugin connects to a Mixfont account in the browser.
# Generations count against the team plan's runs.
#
# https://www.mixfont.com
#
###########################################################################################################

from __future__ import division, print_function, unicode_literals

import json
import os
import random
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

import objc
from AppKit import (
	NSAffineTransform,
	NSBezierPath,
	NSBitmapImageRep,
	NSCalibratedRGBColorSpace,
	NSColor,
	NSFont,
	NSGraphicsContext,
	NSMakeRect,
	NSMenuItem,
	NSWorkspace,
)
from Foundation import NSURL
from GlyphsApp import Glyphs, GLYPH_MENU, Message
from GlyphsApp.plugins import GeneralPlugin

try:
	from AppKit import NSBitmapImageFileTypePNG
except ImportError:
	NSBitmapImageFileTypePNG = 4  # value of the deprecated NSPNGFileType alias

try:
	import vanilla
	HAS_VANILLA = True
except ImportError:
	HAS_VANILLA = False


DEFAULT_API_BASE_URL = "https://www.mixfont.com"

API_BASE_URL_DEFAULTS_KEY = "com.mixfont.glyphs.apiBaseUrl"
PLUGIN_TOKEN_DEFAULTS_KEY = "com.mixfont.glyphs.pluginToken"
STANDARD_GLYPH_SET = "standard"
EXTENDED_GLYPH_SET = "extended"
MAX_REFERENCE_GLYPHS = 24
MAX_UPPERCASE_REFERENCE_GLYPHS = 10
MAX_LOWERCASE_REFERENCE_GLYPHS = 12
UPPERCASE_REFERENCE_CHARS = "HOANESRVTBDGMPCFULKIQJXYZW"
LOWERCASE_REFERENCE_CHARS = "nohaesvrilmcupgydtbkqfjwxyz"

# Reference image layout: a lettersheet drawn black on white. Every line is
# scaled so ascender-to-descender maps to ROW_HEIGHT_PX pixels.
ROW_HEIGHT_PX = 256.0
ROW_GAP_PX = 64.0
MARGIN_PX = 48.0
MAX_ROW_CONTENT_PX = 1952.0
SHEET_TRACKING_PX = 24.0
FALLBACK_ADVANCE_UNITS = 80.0

POLL_INTERVAL_SECONDS = 3.0
JOB_TIMEOUT_SECONDS = 15 * 60
PAIRING_TIMEOUT_SECONDS = 15 * 60
PAIRING_POLL_INTERVAL_SECONDS = 2.5
REQUEST_TIMEOUT_SECONDS = 60
DOWNLOAD_TIMEOUT_SECONDS = 120
USER_AGENT = "MixfontGlyphsPlugin/1.0 (+https://www.mixfont.com)"
STANDARD_ESTIMATED_FONT_GENERATION_DURATION_SECONDS = 60.0
EXTENDED_ESTIMATED_FONT_GENERATION_DURATION_SECONDS = 5.0 * 60.0
MIN_ESTIMATED_PROGRESS_TICK_SECONDS = 0.7
MAX_ESTIMATED_PROGRESS_TICK_SECONDS = 2.4
MAX_ESTIMATED_ACTIVE_PROGRESS_PERCENT = 96.0

STATUS_LABELS = {
	"preparing": "Analyzing reference image",
	"queued": "Waiting in queue",
	"running": "Generating glyphs",
}

CONNECT_BUTTON_TITLE = "Connect Mixfont Account"
DISCONNECT_BUTTON_TITLE = "Logout"
NOT_CONNECTED_LABEL = "Sign in for 50 free credits."


class MixfontApiError(Exception):
	pass


class MixfontAuthError(MixfontApiError):
	pass


def openUrlInBrowser(url):
	NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))


class MixfontPlugin(GeneralPlugin):

	@objc.python_method
	def settings(self):
		self.name = Glyphs.localize({"en": "AI Font Assistant"})

	@objc.python_method
	def start(self):
		self.w = None
		self._jobRunning = False
		self._pairingRunning = False
		self._account = None
		self._progressState = None
		self._progressStateLock = threading.Lock()
		self._progressTickerStop = None

		menuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			Glyphs.localize({"en": "AI Font Assistant…"}),
			self.showWindow_,
			"",
		)
		menuItem.setTarget_(self)
		Glyphs.menu[GLYPH_MENU].append(menuItem)

	def showWindow_(self, sender):
		if not HAS_VANILLA:
			Message(
				"The AI Font Assistant plugin needs the Vanilla module. Choose Window > Plugin Manager > Modules, install Vanilla, and restart Glyphs.",
				title="AI Font Assistant",
				OKButton="OK",
			)
			return
		self.buildWindow()

	# ------------------------------------------------------------------ UI

	@objc.python_method
	def buildWindow(self):
		if self.w is not None:
			try:
				self.w.close()
			except Exception:
				pass
			self.w = None

		self.w = vanilla.FloatingWindow((440, 416), "AI Font Assistant by Mixfont")
		self.w.titleText = vanilla.TextBox((15, 16, -15, 18), "AI Font Assistant", sizeStyle="small")
		self.w.descriptionText = vanilla.TextBox(
			(15, 42, -15, 58),
			"This AI Font Assistant extends a few glyphs into a larger glyph set in the same style. It uses the glyphs in your current project to create an expanded set with AI. The generated font will open in a new project.",
			sizeStyle="small",
		)
		self.w.glyphSetLabel = vanilla.TextBox((15, 112, -15, 17), "Choose a glyph set:", sizeStyle="small")
		self.w.glyphSetRadio = vanilla.RadioGroup(
			(18, 130, 22, 96),
			["", ""],
			isVertical=True,
			sizeStyle="small",
		)
		self.w.glyphSetRadio.set(0)
		self.w.standardGlyphSetTitle = vanilla.TextBox((44, 142, 74, 20), "Standard", sizeStyle="small")
		self.w.standardGlyphSetDescription = vanilla.TextBox(
			(126, 142, -15, 38),
			"Basic Latin letters, numbers, and punctuation. Uses 20 credits.",
			sizeStyle="small",
		)
		self.w.extendedGlyphSetTitle = vanilla.TextBox((44, 194, 74, 20), "Extended", sizeStyle="small")
		self.w.extendedGlyphSetDescription = vanilla.TextBox(
			(126, 194, -15, 38),
			"320+ glyphs across core Latin languages including accents and symbols. Uses 50 credits.",
			sizeStyle="small",
		)
		self.w.standardGlyphSetHitArea = vanilla.Button((38, 138, -15, 44), "", sizeStyle="small", callback=self.selectStandardGlyphSetCallback)
		self.w.extendedGlyphSetHitArea = vanilla.Button((38, 190, -15, 44), "", sizeStyle="small", callback=self.selectExtendedGlyphSetCallback)
		self.configureTransparentButton(self.w.standardGlyphSetHitArea)
		self.configureTransparentButton(self.w.extendedGlyphSetHitArea)
		self.w.generateButton = vanilla.Button((122, 248, 196, 34), "Generate Font", sizeStyle="small", callback=self.generateCallback)
		self.w.warningText = vanilla.TextBox((15, 286, -15, 34), "", sizeStyle="small")
		self.w.status = vanilla.TextBox((15, 326, -15, 24), "", sizeStyle="small")
		self.w.progress = vanilla.ProgressBar((15, 350, -15, 16))
		self.w.accountInfo = vanilla.TextBox((15, 386, 225, 17), NOT_CONNECTED_LABEL, sizeStyle="small")
		self.w.connectButton = vanilla.Button((255, 382, 170, 22), CONNECT_BUTTON_TITLE, sizeStyle="small", callback=self.connectCallback)

		self.setTitleFont()
		self.setWarningTextColor()
		self.configureCenteredTextBox(self.w.warningText)
		self.configureWrappingTextBox(self.w.warningText)
		self.configureWrappingTextBox(self.w.status)
		self.w.progress.set(0)
		self.setProgressVisible(self._jobRunning)
		self.w.setDefaultButton(self.w.generateButton)
		self.updateAccountUi()
		if self._jobRunning:
			self.w.generateButton.enable(False)
			self.setGlyphSetControlsEnabled(False)
			self.setStatus("A Mixfont generation is already running…")
		self.w.open()

		if self.storedToken() and self._account is None:
			self.startAccountRefresh()

	@objc.python_method
	def setStatus(self, text):
		try:
			if self.w is not None:
				self.w.status.set(text)
		except Exception:
			pass

	@objc.python_method
	def setWarningText(self, text):
		try:
			if self.w is not None:
				self.w.warningText.set(text)
		except Exception:
			pass

	@objc.python_method
	def setTitleFont(self):
		try:
			self.w.titleText.getNSTextField().setFont_(NSFont.boldSystemFontOfSize_(12.0))
		except Exception:
			pass

	@objc.python_method
	def setWarningTextColor(self):
		try:
			color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.42, 0.0, 1.0)
			self.w.warningText.getNSTextField().setTextColor_(color)
		except Exception:
			pass

	@objc.python_method
	def configureTransparentButton(self, button):
		try:
			nsButton = button.getNSButton()
			nsButton.setBordered_(False)
			nsButton.setTransparent_(True)
		except Exception:
			pass

	@objc.python_method
	def configureWrappingTextBox(self, textBox):
		try:
			nsTextField = textBox.getNSTextField()
			nsTextField.setUsesSingleLineMode_(False)
			cell = nsTextField.cell()
			cell.setWraps_(True)
			cell.setScrollable_(False)
		except Exception:
			pass

	@objc.python_method
	def configureCenteredTextBox(self, textBox):
		try:
			textBox.getNSTextField().setAlignment_(2)
		except Exception:
			pass

	@objc.python_method
	def setGlyphSetControlsEnabled(self, enabled):
		try:
			if self.w is None:
				return
			self.w.glyphSetRadio.enable(bool(enabled))
			self.w.standardGlyphSetHitArea.enable(bool(enabled))
			self.w.extendedGlyphSetHitArea.enable(bool(enabled))
		except Exception:
			pass

	@objc.python_method
	def selectGlyphSetIndex(self, index):
		try:
			if self.w is not None and not self._jobRunning:
				self.w.glyphSetRadio.set(int(index))
		except Exception:
			pass

	@objc.python_method
	def selectStandardGlyphSetCallback(self, sender):
		self.selectGlyphSetIndex(0)

	@objc.python_method
	def selectExtendedGlyphSetCallback(self, sender):
		self.selectGlyphSetIndex(1)

	@objc.python_method
	def setProgress(self, value):
		try:
			if self.w is not None:
				self.w.progress.set(max(0.0, min(100.0, float(value))))
		except Exception:
			pass

	@objc.python_method
	def setProgressVisible(self, visible):
		try:
			if self.w is not None:
				self.w.progress.show(bool(visible))
		except Exception:
			pass

	@objc.python_method
	def storedToken(self):
		return str(Glyphs.defaults[PLUGIN_TOKEN_DEFAULTS_KEY] or "").strip()

	@objc.python_method
	def accountLabelText(self):
		if not self.storedToken():
			return NOT_CONNECTED_LABEL
		if not self._account:
			return "Loading account…"
		name = self._account.get("name", "")
		email = self._account.get("email", "")
		webCredits = self._account.get("webCredits")
		label = name or email
		credits = "%s credits" % webCredits if webCredits is not None else ""
		if label and credits:
			return "%s · %s" % (label, credits)
		return label or credits or "Connected"

	@objc.python_method
	def updateAccountUi(self):
		try:
			if self.w is None:
				return
			self.w.accountInfo.set(self.accountLabelText())
			if self.storedToken():
				self.w.accountInfo.setPosSize((15, 386, 323, 17))
				self.w.connectButton.setPosSize((353, 382, 72, 22))
				self.w.connectButton.setTitle(DISCONNECT_BUTTON_TITLE)
				self.w.setDefaultButton(self.w.generateButton)
			else:
				self.w.accountInfo.setPosSize((15, 386, 225, 17))
				self.w.connectButton.setPosSize((255, 382, 170, 22))
				self.w.connectButton.setTitle(CONNECT_BUTTON_TITLE)
				self.w.setDefaultButton(self.w.connectButton)
			self.w.connectButton.enable(not self._pairingRunning)
		except Exception:
			pass

	# --------------------------------------------------- account pairing

	@objc.python_method
	def connectCallback(self, sender):
		if self._pairingRunning:
			return
		self.setWarningText("")
		if self.storedToken():
			oldToken = self.storedToken()
			Glyphs.defaults[PLUGIN_TOKEN_DEFAULTS_KEY] = None
			self._account = None
			self.updateAccountUi()
			self.setStatus("")
			worker = threading.Thread(target=self.signOutOnServer, args=(oldToken,), name="MixfontSignOut")
			worker.daemon = True
			worker.start()
			return

		self._pairingRunning = True
		self.updateAccountUi()
		self.setStatus("")
		worker = threading.Thread(target=self.runPairingFlow, name="MixfontPairing")
		worker.daemon = True
		worker.start()

	@objc.python_method
	def signOutOnServer(self, token):
		try:
			self.fetchJson("POST", "%s/api/glyphs/auth/signout" % self.apiBaseUrl(), token=token, body=b"")
		except Exception:
			pass

	@objc.python_method
	def runPairingFlow(self):
		"""Runs on a background thread. Must not touch Glyphs objects or UI directly."""
		try:
			payload = self.fetchJson("POST", "%s/api/glyphs/auth/pairings" % self.apiBaseUrl(), body=b"")
			pairing = payload.get("pairing") if isinstance(payload, dict) else None
			if not pairing:
				raise MixfontApiError("The Mixfont API did not return a connection request.")
			readKey = str(pairing.get("readKey") or "")
			connectUrl = str(pairing.get("connectUrl") or "")
			if not readKey or not connectUrl:
				raise MixfontApiError("The Mixfont API returned an incomplete connection request.")
			try:
				pollInterval = float(pairing.get("pollIntervalMs") or 0) / 1000.0
			except Exception:
				pollInterval = 0.0
			if pollInterval <= 0:
				pollInterval = PAIRING_POLL_INTERVAL_SECONDS

			self.performSelectorOnMainThread_withObject_waitUntilDone_("openPairingUrl:", connectUrl, False)

			deadline = time.time() + PAIRING_TIMEOUT_SECONDS
			while True:
				if time.time() > deadline:
					raise MixfontApiError("The connection request expired. Try connecting again.")
				time.sleep(pollInterval)
				poll = self.fetchJson(
					"GET",
					"%s/api/glyphs/auth/pairings/poll?readKey=%s" % (self.apiBaseUrl(), urllib.parse.quote(readKey)),
				)
				status = str(poll.get("status") or "")
				if status == "approved":
					token = str(poll.get("token") or "")
					if not token:
						raise MixfontApiError("The Mixfont API did not return a token.")
					self.performSelectorOnMainThread_withObject_waitUntilDone_("pairingSucceeded:", {"token": token}, False)
					return
				if status == "expired":
					raise MixfontApiError("The connection request expired. Try connecting again.")
		except MixfontApiError as error:
			self.performSelectorOnMainThread_withObject_waitUntilDone_("pairingFailed:", {"message": str(error)}, False)
		except Exception:
			print("Mixfont: pairing failed")
			print(traceback.format_exc())
			self.performSelectorOnMainThread_withObject_waitUntilDone_(
				"pairingFailed:",
				{"message": "Could not connect. See Window > Macro Panel for details."},
				False,
			)

	def openPairingUrl_(self, urlString):
		try:
			openUrlInBrowser(str(urlString))
		except Exception:
			pass

	def pairingSucceeded_(self, info):
		self._pairingRunning = False
		Glyphs.defaults[PLUGIN_TOKEN_DEFAULTS_KEY] = str(info["token"])
		self.updateAccountUi()
		self.setStatus("")
		self.startAccountRefresh()

	def pairingFailed_(self, info):
		self._pairingRunning = False
		self.updateAccountUi()
		try:
			self.setStatus(str(info["message"]))
		except Exception:
			pass

	@objc.python_method
	def startAccountRefresh(self):
		token = self.storedToken()
		if not token:
			return
		worker = threading.Thread(target=self.refreshAccountInfo, args=(token,), name="MixfontAccount")
		worker.daemon = True
		worker.start()

	@objc.python_method
	def refreshAccountInfo(self, token):
		"""Runs on a background thread."""
		try:
			payload = self.fetchJson("GET", "%s/api/glyphs/me" % self.apiBaseUrl(), token=token)
			account = payload.get("account") if isinstance(payload, dict) else None
			if not account:
				return
			info = {
				"email": str(account.get("email") or ""),
				"name": str(account.get("name") or ""),
				"teamName": str((account.get("team") or {}).get("name") or ""),
				"planLabel": str((account.get("plan") or {}).get("label") or ""),
			}
			usage = account.get("usage") or {}
			webCredits = usage.get("webCredits")
			webCreditsLimit = usage.get("webCreditsLimit")
			if webCredits is not None:
				info["webCredits"] = str(int(webCredits))
			if webCreditsLimit is not None:
				info["webCreditsLimit"] = str(int(webCreditsLimit))
			self.performSelectorOnMainThread_withObject_waitUntilDone_("accountUpdated:", info, False)
		except MixfontAuthError:
			self.performSelectorOnMainThread_withObject_waitUntilDone_(
				"authFailed:",
				{"message": "Your Mixfont connection expired. Connect your account again."},
				False,
			)
		except Exception:
			pass

	def accountUpdated_(self, info):
		try:
			self._account = {
				"email": str(info["email"]),
				"name": str(info["name"]),
				"teamName": str(info["teamName"]),
				"planLabel": str(info["planLabel"]),
				"webCredits": str(info["webCredits"]) if "webCredits" in info else None,
				"webCreditsLimit": str(info["webCreditsLimit"]) if "webCreditsLimit" in info else None,
			}
		except Exception:
			self._account = None
		self.updateAccountUi()

	def authFailed_(self, info):
		self._jobRunning = False
		self._pairingRunning = False
		Glyphs.defaults[PLUGIN_TOKEN_DEFAULTS_KEY] = None
		self._account = None
		self.updateAccountUi()
		try:
			self.setStatus(str(info["message"]))
			self.setProgress(0)
			self.setProgressVisible(False)
			if self.w is not None:
				self.w.generateButton.enable(True)
				self.setGlyphSetControlsEnabled(True)
		except Exception:
			pass

	# ---------------------------------------------------- source + rendering

	@objc.python_method
	def sourceLayersForFont(self, font):
		"""Current-master layers used as the style reference: a capped,
		representative set of drawn letters."""
		if font is None:
			return []
		master = font.selectedFontMaster or font.masters[0]
		layers = []
		for glyph in list(font.glyphs):
			layer = glyph.layers[master.id]
			if layer is None:
				continue
			bezierPath = layer.completeBezierPath
			if bezierPath is None or bezierPath.elementCount() == 0:
				continue
			if self.letterForGlyph(glyph):
				layers.append(layer)
		return self.referenceSubsetForLayers(layers)

	@objc.python_method
	def letterForGlyph(self, glyph):
		char = glyph.string
		if char:
			char = str(char)
		if char and len(char) == 1 and char.isalpha():
			return char
		unicodeValue = glyph.unicode
		if unicodeValue:
			try:
				if isinstance(unicodeValue, int):
					char = chr(unicodeValue)
				else:
					char = chr(int(str(unicodeValue), 16))
				if char and char.isalpha():
					return char
			except Exception:
				pass
		return None

	@objc.python_method
	def referenceSubsetForLayers(self, layers):
		if len(layers) <= MAX_REFERENCE_GLYPHS:
			return layers

		selected = []
		selectedNames = set()
		self.addPriorityReferenceLayers(
			selected,
			selectedNames,
			layers,
			UPPERCASE_REFERENCE_CHARS,
			MAX_UPPERCASE_REFERENCE_GLYPHS,
		)
		self.addPriorityReferenceLayers(
			selected,
			selectedNames,
			layers,
			LOWERCASE_REFERENCE_CHARS,
			MAX_LOWERCASE_REFERENCE_GLYPHS,
		)
		for layer in layers:
			if len(selected) >= MAX_REFERENCE_GLYPHS:
				break
			glyphName = layer.parent.name
			if glyphName in selectedNames:
				continue
			selected.append(layer)
			selectedNames.add(glyphName)
		return selected

	@objc.python_method
	def addPriorityReferenceLayers(self, selected, selectedNames, layers, chars, limit):
		for char in chars:
			if len(selected) >= MAX_REFERENCE_GLYPHS or limit <= 0:
				return
			for layer in layers:
				glyph = layer.parent
				glyphName = glyph.name
				if glyphName in selectedNames:
					continue
				if self.letterForGlyph(glyph) != char:
					continue
				selected.append(layer)
				selectedNames.add(glyphName)
				limit -= 1
				break

	@objc.python_method
	def advanceUnitsForLayer(self, layer):
		advance = layer.width
		if advance and advance > 0:
			return advance
		return layer.bounds.size.width + FALLBACK_ADVANCE_UNITS

	@objc.python_method
	def composeReferenceLines(self, layers, scale):
		"""Arranges the source layers into lettersheet lines of (layers,
		trackingPx), wrapped to the row width."""
		lines = []
		row = []
		penX = 0.0
		for layer in layers:
			advancePx = self.advanceUnitsForLayer(layer) * scale
			if row and penX + advancePx > MAX_ROW_CONTENT_PX:
				lines.append((row, SHEET_TRACKING_PX))
				row = []
				penX = 0.0
			row.append(layer)
			penX += advancePx + SHEET_TRACKING_PX
		if row:
			lines.append((row, SHEET_TRACKING_PX))

		return lines

	@objc.python_method
	def renderReferenceImage(self, layers, master):
		rowUnits = (master.ascender or 0) - (master.descender or 0)
		if rowUnits <= 0:
			rowUnits = layers[0].parent.parent.upm or 1000
		scale = ROW_HEIGHT_PX / rowUnits

		rows = []
		contentWidth = 0.0
		for lineLayers, trackingPx in self.composeReferenceLines(layers, scale):
			penX = 0.0
			placed = []
			for layer in lineLayers:
				placed.append((layer, penX))
				penX += self.advanceUnitsForLayer(layer) * scale + trackingPx
			rows.append(placed)
			contentWidth = max(contentWidth, penX - trackingPx)

		imageWidth = int(round(contentWidth + 2 * MARGIN_PX))
		imageHeight = int(round(2 * MARGIN_PX + len(rows) * ROW_HEIGHT_PX + (len(rows) - 1) * ROW_GAP_PX))

		bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bitmapFormat_bytesPerRow_bitsPerPixel_(
			None, imageWidth, imageHeight, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 4 * imageWidth, 32,
		)
		if bitmap is None:
			raise MixfontApiError("Could not create the reference image bitmap.")

		originalContext = NSGraphicsContext.currentContext()
		NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap))
		try:
			NSColor.whiteColor().set()
			NSBezierPath.bezierPathWithRect_(NSMakeRect(0, 0, imageWidth, imageHeight)).fill()
			NSColor.blackColor().set()
			for rowIndex, row in enumerate(rows):
				rowBottom = imageHeight - MARGIN_PX - ROW_HEIGHT_PX - rowIndex * (ROW_HEIGHT_PX + ROW_GAP_PX)
				for layer, xOffset in row:
					path = layer.completeBezierPath.copy()
					shiftToBaseline = NSAffineTransform.transform()
					shiftToBaseline.translateXBy_yBy_(0.0, -(master.descender or 0))
					path.transformUsingAffineTransform_(shiftToBaseline)
					scaleToPixels = NSAffineTransform.transform()
					scaleToPixels.scaleBy_(scale)
					path.transformUsingAffineTransform_(scaleToPixels)
					moveToPen = NSAffineTransform.transform()
					moveToPen.translateXBy_yBy_(MARGIN_PX + xOffset, rowBottom)
					path.transformUsingAffineTransform_(moveToPen)
					path.fill()
		finally:
			NSGraphicsContext.setCurrentContext_(originalContext)

		pngData = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
		if pngData is None:
			raise MixfontApiError("Could not encode the reference image as PNG.")
		pngBytes = self.nsdataToBytes(pngData)

		try:
			debugPath = os.path.join(tempfile.gettempdir(), "mixfont-reference.png")
			with open(debugPath, "wb") as debugFile:
				debugFile.write(pngBytes)
			print("Mixfont: reference image written to %s" % debugPath)
		except Exception:
			pass

		return pngBytes

	@objc.python_method
	def nsdataToBytes(self, data):
		try:
			return bytes(data)
		except Exception:
			return data.bytes().tobytes()

	# ------------------------------------------------------------ generation

	@objc.python_method
	def generateCallback(self, sender):
		if self._jobRunning:
			return
		glyphSet = self.selectedGlyphSet()
		font = Glyphs.font
		layers = self.sourceLayersForFont(font)
		if not layers:
			self.showMissingGlyphsWarning()
			return
		token = self.storedToken()
		if not token:
			self.setWarningText("")
			self.promptForConnection()
			return

		self.setWarningText("")
		master = font.selectedFontMaster or font.masters[0]
		try:
			pngBytes = self.renderReferenceImage(layers, master)
		except Exception:
			print("Mixfont: failed to render the reference image")
			print(traceback.format_exc())
			self.setStatus("Could not render the font glyphs. See Window > Macro Panel.")
			return

		self._jobRunning = True
		self.w.generateButton.enable(False)
		self.setGlyphSetControlsEnabled(False)
		self.setProgressVisible(True)
		self.setProgress(2)
		self.setStatus("Uploading reference image…")

		worker = threading.Thread(
			target=self.runGenerationJob,
			args=(token, pngBytes, glyphSet),
			name="MixfontGenerationJob",
		)
		worker.daemon = True
		worker.start()

	@objc.python_method
	def selectedGlyphSet(self):
		try:
			if self.w is not None and int(self.w.glyphSetRadio.get()) == 1:
				return EXTENDED_GLYPH_SET
		except Exception:
			pass
		return STANDARD_GLYPH_SET

	@objc.python_method
	def showMissingGlyphsWarning(self):
		self.setWarningText("Add a few sample letter glyphs or open a font file first.")
		self.setStatus("")

	@objc.python_method
	def promptForConnection(self):
		self.setWarningText("To start generating, please first connect your Mixfont account. You can sign in or create an account for free using the button at the bottom of the plugin.")
		self.setStatus("")

	@objc.python_method
	def apiBaseUrl(self):
		base = Glyphs.defaults[API_BASE_URL_DEFAULTS_KEY] or DEFAULT_API_BASE_URL
		return str(base).rstrip("/")

	@objc.python_method
	def generatedFontName(self, generation):
		try:
			name = str(generation.get("name") or "").strip()
		except Exception:
			name = ""
		return name or "Mixfont Generation"

	@objc.python_method
	def safeFileName(self, value):
		name = str(value or "").strip()
		parts = []
		lastWasSeparator = False
		for char in name:
			if char.isalnum():
				parts.append(char)
				lastWasSeparator = False
			elif not lastWasSeparator:
				parts.append("-")
				lastWasSeparator = True
		safeName = "".join(parts).strip("-")
		return safeName[:80] or "mixfont-generation"

	@objc.python_method
	def estimatedGenerationDurationSeconds(self, glyphSet):
		if glyphSet == EXTENDED_GLYPH_SET:
			return EXTENDED_ESTIMATED_FONT_GENERATION_DURATION_SECONDS
		return STANDARD_ESTIMATED_FONT_GENERATION_DURATION_SECONDS

	@objc.python_method
	def normalizedProgress(self, progress):
		try:
			value = float(progress)
		except Exception:
			value = 0.0
		return max(0.0, min(100.0, value))

	@objc.python_method
	def progressLabelForGeneration(self, generation):
		status = str(generation.get("status") or "")
		return STATUS_LABELS.get(status, "Generating")

	@objc.python_method
	def progressValueForGeneration(self, generation):
		return self.normalizedProgress(generation.get("progressPercent") or 0)

	@objc.python_method
	def formatProgressStatus(self, label, progress):
		return "%s… %i%%" % (label, int(round(self.normalizedProgress(progress))))

	@objc.python_method
	def startEstimatedProgressTicker(self, jobId, glyphSet, generation):
		self.stopEstimatedProgressTicker()
		label = self.progressLabelForGeneration(generation)
		progress = max(5.0, self.progressValueForGeneration(generation))
		stopEvent = threading.Event()
		with self._progressStateLock:
			self._progressState = {
				"jobId": jobId,
				"label": label,
				"progress": progress,
			}
			self._progressTickerStop = stopEvent
		self.postStatus(self.formatProgressStatus(label, progress), progress)
		worker = threading.Thread(
			target=self.runEstimatedProgressTicker,
			args=(jobId, glyphSet, stopEvent),
			name="MixfontProgressTicker",
		)
		worker.daemon = True
		worker.start()

	@objc.python_method
	def stopEstimatedProgressTicker(self):
		try:
			stopEvent = self._progressTickerStop
			if stopEvent is not None:
				stopEvent.set()
		except Exception:
			pass
		try:
			with self._progressStateLock:
				self._progressTickerStop = None
				self._progressState = None
		except Exception:
			pass

	@objc.python_method
	def runEstimatedProgressTicker(self, jobId, glyphSet, stopEvent):
		estimatedDurationSeconds = self.estimatedGenerationDurationSeconds(glyphSet)
		lastTickAt = time.time()
		while True:
			tickDelay = random.uniform(
				MIN_ESTIMATED_PROGRESS_TICK_SECONDS,
				MAX_ESTIMATED_PROGRESS_TICK_SECONDS,
			)
			if stopEvent.wait(tickDelay):
				return
			tickedAt = time.time()
			elapsedSeconds = max(0.0, tickedAt - lastTickAt)
			lastTickAt = tickedAt
			shouldPost = False
			label = "Generating"
			progress = 0.0
			with self._progressStateLock:
				state = self._progressState
				if (
					state is None or
					state.get("jobId") != jobId or
					stopEvent.is_set()
				):
					return
				currentProgress = self.normalizedProgress(state.get("progress") or 0)
				nextProgress = min(
					MAX_ESTIMATED_ACTIVE_PROGRESS_PERCENT,
					currentProgress + (elapsedSeconds / estimatedDurationSeconds) * 100.0,
				)
				if nextProgress > currentProgress:
					state["progress"] = nextProgress
					label = str(state.get("label") or "Generating")
					progress = nextProgress
					shouldPost = True
			if shouldPost and not stopEvent.is_set():
				self.postStatus(self.formatProgressStatus(label, progress), progress)

	@objc.python_method
	def updateEstimatedProgressFromGeneration(self, jobId, generation):
		label = self.progressLabelForGeneration(generation)
		backendProgress = max(5.0, self.progressValueForGeneration(generation))
		progress = backendProgress
		with self._progressStateLock:
			state = self._progressState
			if state is not None and state.get("jobId") == jobId:
				progress = max(
					self.normalizedProgress(state.get("progress") or 0),
					backendProgress,
				)
				state["label"] = label
				state["progress"] = progress
		self.postStatus(self.formatProgressStatus(label, progress), progress)

	@objc.python_method
	def runGenerationJob(self, token, pngBytes, glyphSet):
		"""Runs on a background thread. Must not touch Glyphs objects or UI directly."""
		jobId = None
		try:
			generation = self.createGenerationJob(token, pngBytes, glyphSet)
			jobId = str(generation.get("id") or "")
			if not jobId:
				raise MixfontApiError("The Mixfont API did not return a job id.")
			pollUrl = "%s/api/glyphs/font-generations/%s" % (self.apiBaseUrl(), jobId)
			self.startEstimatedProgressTicker(jobId, glyphSet, generation)

			deadline = time.time() + JOB_TIMEOUT_SECONDS
			ttfUrl = None
			while True:
				status = str(generation.get("status") or "")
				if status == "succeeded":
					self.stopEstimatedProgressTicker()
					ttfUrl = generation.get("ttfUrl")
					if ttfUrl:
						break
					self.postStatus("Finalizing font…", 99)
				elif status in ("failed", "cancelled"):
					raise MixfontApiError(str(generation.get("error") or ("Generation %s." % status)))
				else:
					self.updateEstimatedProgressFromGeneration(jobId, generation)
				if time.time() > deadline:
					raise MixfontApiError("Timed out waiting for the generation to finish.")
				time.sleep(POLL_INTERVAL_SECONDS)
				generation = self.fetchGeneration(token, pollUrl)

			self.postStatus("Downloading generated font…", 97)
			downloadUrl = "%s/api/glyphs/font-generations/%s/font" % (self.apiBaseUrl(), jobId)
			fontName = self.generatedFontName(generation)
			ttfPath = self.downloadTtf(downloadUrl, jobId, token, fontName)
			self.postStatus("Opening generated font…", 98)
			self.performSelectorOnMainThread_withObject_waitUntilDone_("importGeneratedFont:", {"path": ttfPath, "name": fontName}, False)
		except MixfontAuthError as error:
			self.stopEstimatedProgressTicker()
			self.performSelectorOnMainThread_withObject_waitUntilDone_("authFailed:", {"message": str(error)}, False)
		except MixfontApiError as error:
			self.stopEstimatedProgressTicker()
			self.performSelectorOnMainThread_withObject_waitUntilDone_("finishJobWithError:", {"message": str(error)}, False)
		except Exception:
			self.stopEstimatedProgressTicker()
			print("Mixfont: generation job failed")
			print(traceback.format_exc())
			self.performSelectorOnMainThread_withObject_waitUntilDone_(
				"finishJobWithError:",
				{"message": "Unexpected error. See Window > Macro Panel for details."},
				False,
			)

	@objc.python_method
	def fetchGeneration(self, token, url):
		payload = self.fetchJson("GET", url, token=token)
		generation = payload.get("generation") if isinstance(payload, dict) else None
		if not isinstance(generation, dict):
			raise MixfontApiError("The Mixfont API returned an unexpected response.")
		return generation

	@objc.python_method
	def createGenerationJob(self, token, pngBytes, glyphSet):
		boundary = "mixfont%s" % uuid.uuid4().hex
		parts = []
		for fieldName, fieldValue in (("input_type", "image"), ("glyph_set", glyphSet)):
			parts.append((
				"--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
				% (boundary, fieldName, fieldValue)
			).encode("utf-8"))
		parts.append((
			"--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"glyph-reference.png\"\r\n"
			"Content-Type: image/png\r\n\r\n" % boundary
		).encode("utf-8"))
		parts.append(pngBytes)
		parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
		body = b"".join(parts)

		payload = self.fetchJson(
			"POST",
			"%s/api/glyphs/font-generations" % self.apiBaseUrl(),
			token=token,
			body=body,
			contentType="multipart/form-data; boundary=%s" % boundary,
		)
		generation = payload.get("generation") if isinstance(payload, dict) else None
		if not isinstance(generation, dict):
			raise MixfontApiError("The Mixfont API returned an unexpected response.")
		return generation

	@objc.python_method
	def fetchJson(self, method, url, token=None, body=None, contentType=None):
		headers = {
			"Accept": "application/json",
			"User-Agent": USER_AGENT,
		}
		if token:
			headers["Authorization"] = "Bearer %s" % token
		if contentType:
			headers["Content-Type"] = contentType
		request = urllib.request.Request(url, data=body, headers=headers, method=method)
		try:
			with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
				payload = response.read()
		except urllib.error.HTTPError as error:
			if error.code == 401 and token:
				raise MixfontAuthError("Your Mixfont connection expired. Connect your account again.")
			raise MixfontApiError(self.readHttpErrorMessage(error))
		except urllib.error.URLError as error:
			raise MixfontApiError("Could not reach Mixfont (%s)." % getattr(error, "reason", error))
		try:
			return json.loads(payload.decode("utf-8"))
		except ValueError:
			raise MixfontApiError("The Mixfont API returned an unexpected response.")

	@objc.python_method
	def readHttpErrorMessage(self, error):
		message = ""
		try:
			payload = json.loads(error.read().decode("utf-8"))
			message = str(payload.get("error") or "")
		except Exception:
			message = ""
		if error.code == 402:
			return message or "Not enough credits for this generation."
		if error.code == 429:
			return message or "Your team has reached its font generation limit."
		return message or ("The Mixfont API returned HTTP %i." % error.code)

	@objc.python_method
	def downloadTtf(self, ttfUrl, jobId, token=None, fontName=None):
		headers = {"User-Agent": USER_AGENT}
		if token:
			headers["Authorization"] = "Bearer %s" % token
		request = urllib.request.Request(ttfUrl, headers=headers)
		try:
			with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
				data = response.read()
		except (urllib.error.HTTPError, urllib.error.URLError) as error:
			raise MixfontApiError("Could not download the generated font (%s)." % error)
		if not data:
			raise MixfontApiError("The downloaded font file was empty.")
		path = os.path.join(tempfile.gettempdir(), "%s.ttf" % self.safeFileName(fontName or jobId))
		with open(path, "wb") as ttfFile:
			ttfFile.write(data)
		return path

	@objc.python_method
	def postStatus(self, text, progress):
		self.performSelectorOnMainThread_withObject_waitUntilDone_(
			"updateJobStatus:",
			{"text": text, "progress": float(progress)},
			False,
		)

	# ----------------------------------------------- main-thread callbacks

	def updateJobStatus_(self, info):
		try:
			self.setStatus(str(info["text"]))
			self.setProgress(float(info["progress"]))
		except Exception:
			pass

	def finishJobWithError_(self, info):
		self._jobRunning = False
		try:
			self.setStatus(str(info["message"]))
			self.setProgress(0)
			self.setProgressVisible(False)
			if self.w is not None:
				self.w.generateButton.enable(True)
				self.setGlyphSetControlsEnabled(True)
		except Exception:
			pass

	def importGeneratedFont_(self, info):
		path = str(info["path"])
		fontName = str(info.get("name") or "").strip() or "Mixfont Generation"
		try:
			summary = self.openGeneratedFontAsNew(path, fontName)
		except MixfontApiError as error:
			self.finishJobWithError_({"message": str(error)})
			return
		except Exception:
			print("Mixfont: failed to import the generated font")
			print(traceback.format_exc())
			self.finishJobWithError_({"message": "Could not import the generated font. See Window > Macro Panel."})
			return

		self._jobRunning = False
		self.setStatus(summary)
		self.setProgress(100)
		self.setProgressVisible(False)
		try:
			if self.w is not None:
				self.w.generateButton.enable(True)
				self.setGlyphSetControlsEnabled(True)
		except Exception:
			pass
		try:
			Glyphs.showNotification("Mixfont", summary)
		except Exception:
			pass
		self.startAccountRefresh()

	# ------------------------------------------------------------- import

	@objc.python_method
	def openGeneratedFontAsNew(self, path, fontName):
		newFont = Glyphs.open(path, True)
		if newFont is None:
			raise MixfontApiError("Glyphs could not open the generated TTF.")
		fontName = str(fontName or "").strip() or "Mixfont Generation"
		try:
			newFont.familyName = fontName
		except Exception:
			pass
		return "Opened “%s” as a new font. You can save it as a .glyphs file to keep editing it." % fontName

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
