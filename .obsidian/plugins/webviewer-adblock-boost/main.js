const { Plugin } = require('obsidian');

const BLOCK_SCRIPT = `
(() => {
  if (window.__webviewerYtAdblockPatched) return;
  window.__webviewerYtAdblockPatched = true;

  const host = location.hostname.toLowerCase();
  const isYouTubeHost =
    host === 'youtube.com' ||
    host.endsWith('.youtube.com') ||
    host === 'youtu.be' ||
    host === 'youtubekids.com' ||
    host.endsWith('.youtubekids.com');
  if (!isYouTubeHost) return;

  // Based on vBlockTube core removal rules for player response payloads.
  const AD_KEYS = new Set([
    'playerAds',
    'adPlacements',
    'adSlots',
    'adBreakHeartbeatParams',
    'adSlotRenderer',
    'mealbarPromoRenderer',
    'companionAds'
  ]);

  const PLAYER_ENDPOINT_TOKENS = [
    '/youtubei/v1/player',
    '/youtubei/v1/next',
    '/youtubei/v1/browse'
  ];

  function shouldSanitizeResponse(urlString) {
    const normalized = String(urlString || '').toLowerCase();
    return PLAYER_ENDPOINT_TOKENS.some((token) => normalized.includes(token));
  }

  function isAdObject(value) {
    return Boolean(
      value &&
      typeof value === 'object' &&
      (
        value.isAd === true ||
        value.adSlotRenderer ||
        value.promotedSparklesTextSearchRenderer ||
        value.displayAdRenderer
      )
    );
  }

  function scrubDeep(value, seen = new WeakSet()) {
    if (!value || typeof value !== 'object') return value;
    if (seen.has(value)) return value;
    seen.add(value);

    if (Array.isArray(value)) {
      for (let i = value.length - 1; i >= 0; i -= 1) {
        if (isAdObject(value[i])) {
          value.splice(i, 1);
          continue;
        }
        scrubDeep(value[i], seen);
      }
      return value;
    }

    Object.keys(value).forEach((key) => {
      if (AD_KEYS.has(key)) {
        delete value[key];
        return;
      }
      if (isAdObject(value[key])) {
        delete value[key];
        return;
      }
      scrubDeep(value[key], seen);
    });
    return value;
  }

  function hookWindowProperty(propName) {
    let currentValue = scrubDeep(window[propName]);
    try {
      Object.defineProperty(window, propName, {
        configurable: true,
        enumerable: true,
        get() {
          return currentValue;
        },
        set(nextValue) {
          currentValue = scrubDeep(nextValue);
        }
      });
    } catch (_error) {}
  }

  hookWindowProperty('ytInitialPlayerResponse');
  hookWindowProperty('ytInitialData');
  hookWindowProperty('ytInitialReelWatchSequenceResponse');

  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  if (nativeFetch) {
    window.fetch = async function patchedFetch(input, init) {
      const url = typeof input === 'string' ? input : (input && input.url);
      const response = await nativeFetch(input, init);
      if (!shouldSanitizeResponse(url)) return response;

      const originalJson = response.json.bind(response);
      response.json = async function patchedJson() {
        const data = await originalJson();
        return scrubDeep(data);
      };
      return response;
    };
  }

  const nativeXhrOpen = XMLHttpRequest.prototype.open;
  const nativeXhrSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
    this.__wvabUrl = url;
    return nativeXhrOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function patchedSend(...args) {
    this.addEventListener('readystatechange', () => {
      if (this.readyState !== 4 || !shouldSanitizeResponse(this.__wvabUrl)) return;
      if (this.responseType && this.responseType !== '' && this.responseType !== 'text') return;
      try {
        const parsed = JSON.parse(this.responseText);
        const cleaned = scrubDeep(parsed);
        const json = JSON.stringify(cleaned);
        Object.defineProperty(this, 'responseText', { configurable: true, get: () => json });
        Object.defineProperty(this, 'response', { configurable: true, get: () => json });
      } catch (_error) {}
    }, { once: true });

    return nativeXhrSend.apply(this, args);
  };

  const AD_OVERLAY_SELECTORS = [
    '.ytp-ad-overlay-container',
    '.ytp-ad-player-overlay',
    '.ytd-display-ad-renderer',
    '.ytd-promoted-sparkles-web-renderer'
  ];

  function removeAdOverlays() {
    AD_OVERLAY_SELECTORS.forEach((selector) => {
      document.querySelectorAll(selector).forEach((el) => el.remove());
    });
  }

  function skipVideoAdIfNeeded() {
    const player = document.querySelector('.html5-video-player');
    if (!player || !player.classList.contains('ad-showing')) return;

    const video = document.querySelector('video');
    if (video && Number.isFinite(video.duration) && video.duration > 0) {
      video.currentTime = video.duration;
    }

    const skipButton = document.querySelector('.ytp-ad-skip-button, .ytp-ad-skip-button-modern');
    if (skipButton) skipButton.click();
  }

  setInterval(() => {
    removeAdOverlays();
    skipVideoAdIfNeeded();
  }, 800);
})();
`;

class WebViewerAdblockBoostPlugin extends Plugin {
  async onload() {
    this.patchedWebviews = new WeakSet();
    this.observeWebviewerDom();
    this.scanAndPatchWebviews();
    this.registerInterval(window.setInterval(() => this.scanAndPatchWebviews(), 1500));
  }

  onunload() {
    if (this.domObserver) {
      this.domObserver.disconnect();
      this.domObserver = null;
    }
  }

  observeWebviewerDom() {
    const root = this.app.workspace?.containerEl;
    if (!root) return;
    this.domObserver = new MutationObserver(() => this.scanAndPatchWebviews());
    this.domObserver.observe(root, { childList: true, subtree: true });
    this.register(() => this.domObserver && this.domObserver.disconnect());
  }

  scanAndPatchWebviews() {
    const root = this.app.workspace?.containerEl;
    if (!root) return;
    const webviews = root.querySelectorAll('webview');
    webviews.forEach((webview) => {
      if (!this.isWebviewerWebview(webview) || this.patchedWebviews.has(webview)) return;
      this.patchWebview(webview);
    });
  }

  isWebviewerWebview(webview) {
    return Boolean(
      webview.closest('.webviewer-content') ||
      webview.closest('[data-type="webviewer"]') ||
      webview.closest('.workspace-leaf-content[data-type="webviewer"]') ||
      webview.closest('.netClip_webview_container') ||
      webview.closest('.workspace-leaf-content[data-type="netClip_workspace_webview"]')
    );
  }

  patchWebview(webview) {
    this.patchedWebviews.add(webview);
    const inject = () => {
      webview.executeJavaScript(BLOCK_SCRIPT).catch((error) => {
        console.warn('[webviewer-adblock-boost] Injection failed:', error);
      });
    };
    webview.addEventListener('dom-ready', inject);
    this.register(() => webview.removeEventListener('dom-ready', inject));
    if (webview.isLoading && !webview.isLoading()) {
      inject();
    }
  }
}

module.exports = WebViewerAdblockBoostPlugin;
