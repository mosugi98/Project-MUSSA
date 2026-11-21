# Make MUSSA look the way you want

MUSSA ships with a green and yellow look: rounded corners, glossy buttons, smooth hover and press
animations. Everything is adjustable from inside the app. You do not need to edit code.

## 1. Open the Appearance window

Click **Appearance** in the top toolbar. Every change is applied to the whole app immediately, so you
can watch the main window while you adjust.

## 2. Choose a starting point

| Preset | Look |
|---|---|
| **Meadow (light)** | Pale green window, white cards, deep green buttons, warm yellow accent. Best in a bright room. |
| **Forest (dark)** | Dark green window, brighter green and yellow. Easier on the eyes in a dim cath lab. |

Picking a preset replaces the six colors but keeps your roundness, gloss, animation and text size.

## 3. Adjust the colors

Click a color button to open the color picker.

| Color | Where it shows |
|---|---|
| Main green | Buttons, toolbar, selected segments, headings, sliders |
| Yellow accent | Selected list rows, checked buttons (such as the chosen answer), the Confirm button, focus ring |
| Window background | Behind everything |
| Cards and lists | Lists, input boxes, panels |
| Text | All normal text |
| Text on green buttons | The label on green buttons and headers |

Shades (lighter top of a button, darker edge, hover color) are worked out from these six, so you only
choose the main colors.

## 4. Shape and feel

- **Roundness of corners**: 4 px (almost square) to 24 px (pill shaped). 14 is the default.
- **Gloss**: 0 is flat. 100 is a strong shine on the top half of every button.
- **Animation speed**: how long hover, press and fade effects take. Around 120 to 200 ms feels smooth.
  Set it to 0 to turn animations off (useful on a slow PC).
- **Text size**: 9 to 16 pt. Pick a larger size for a tablet or for reading from a distance.

## 5. Check readability

The **Readability** box shows the contrast of each text and background pair. Aim for 4.5:1 or more.
A line marked **Low** means text will be hard to read. In a cath lab the screen may be dim or seen at an
angle, so stronger contrast is safer than a prettier color.

## 6. Keep it or undo it

- **Save** writes `theme.json` in your MUSSA data folder (`C:\Users\<you>\MUSSA-data`). It is used from
  the next start.
- **Undo changes** returns to how the app looked when you opened the window.
- **Reset to preset** returns to the chosen preset's defaults.
- Closing without saving keeps the look for this session only.

If `theme.json` is damaged or has a wrong value, MUSSA falls back to the preset for that value and
tells you in the status bar. Deleting the file restores the default look.

## 7. A good way to find your design

1. Start from a preset closest to your idea.
2. Change **one** thing at a time: first the two main colors, then roundness, then gloss.
3. Keep the yellow for things that mean "chosen" or "important". If everything is yellow, nothing stands out.
4. Look at the app in the room where it will be used, and on the tablet if you use one.
5. Save when you like it. Copy `theme.json` to another PC to get the same look there.

Suggested starting points to try:

| Idea | Primary | Accent | Roundness | Gloss |
|---|---|---|---|---|
| Fresh and soft | `#2E8B57` | `#FFE066` | 20 | 70 |
| Clinical and calm | `#1F6F5C` | `#F2C94C` | 10 | 30 |
| Bold and glossy | `#0F9D58` | `#FFD600` | 24 | 100 |
| Flat and quiet | `#2E7D32` | `#FBC02D` | 8 | 0 |

## For developers

- `src/cagsyntax/ui/theme.py`: the tokens, color maths, presets, contrast checks, `theme.json` loading and
  the stylesheet. No Qt, so it is fully unit tested.
- `src/cagsyntax/ui/widgets.py`: `GlossyButton` (painted rounded and glossy, with animated hover and press)
  and `fade_in`.
- `src/cagsyntax/ui/appearance_dialog.py`: the Appearance window.
- To add a new design token, add it to `Theme`, to `COLOR_TOKENS` or `LIMITS`, and use it in `_QSS`.
- Use `GlossyButton(text, variant="primary" | "accent" | "neutral")` for new buttons so they follow the theme.
