# Voice commands

Photo Manager's culling viewer has an optional browser speech-recognition mode.
Voice is an interaction layer over the same semantic actions used by the normal
mouse, keyboard, and touch controls; it does not click DOM controls or persist
transcripts.

## Use

1. Open a photo viewer or a compare view.
2. Press **Enable Voice Mode** in the viewer toolbar.
3. Speak one of the commands shown by **Voice help**.
4. Press **Disable Voice Mode** when finished.

The first enable requests microphone permission. Recognition availability and
privacy behaviour are controlled by the browser vendor. The default language
is `en-GB`. Voice commands are exact matches in V1; low-confidence results,
ambiguous phrases, unavailable actions, and unsupported browsers are reported
without changing the culling state.

## Viewer commands

| Action | Phrases |
| --- | --- |
| Next | `next`, `next photo`, `next picture` |
| Previous | `previous`, `previous photo`, `back` |
| Pick | `pick`, `pick this`, `choose this` |
| Reject | `reject`, `reject this` |
| Zoom in | `zoom in`, `closer` |
| Zoom out | `zoom out` |
| Fit | `fit`, `fit image`, `reset zoom` |
| Original | `original`, `show original` |
| Close | `close`, `close viewer`, `exit` |

## Compare commands

Compare mode supports the navigation, zoom, fit, original, and close commands
above, plus:

| Action | Phrases |
| --- | --- |
| Keep left/current best | `left`, `pick left`, `choose left`, `keep left`, `keep best`, `current best` |
| Keep right/challenger | `right`, `pick right`, `prefer right`, `keep right`, `challenger` |

`next` and `previous` only navigate compare candidates. They never change the
current winner.

## Development

Run the focused voice tests and syntax checks with:

```sh
node --experimental-default-type=module tests/test_voice_core.mjs
node --check src/photovault/web/static/culling.js
node --check src/photovault/web/static/culling_voice.js
```

The browser module is loaded after `culling.js` and is intentionally absent
from grid mode. If the viewer closes or its context becomes unavailable, voice
stops and will not restart until the user explicitly enables it again.
