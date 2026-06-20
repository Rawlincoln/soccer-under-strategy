/**
 * 1xBet app opener — user tap launches the native app (no auto-redirect to browser).
 */
(function () {
  const data = window.ONEXBET_OPEN || {};
  const httpsUrl = data.https || "";
  const intentUrl = data.intent || "";
  const androidAppUrl = data.android_app || "";
  const pkg = data.package || "";
  const playStoreUrl = data.play_store || "";

  const ua = navigator.userAgent || "";
  const isAndroid = /Android/i.test(ua);
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  const inAppBrowser = /Telegram|WhatsApp|FBAN|FBAV|Instagram|Line\//i.test(ua);

  function $(id) {
    return document.getElementById(id);
  }

  function show(el, on) {
    if (el) el.hidden = !on;
  }

  function tryNavigate(url) {
    if (!url) return;
    window.location.href = url;
  }

  function tryIframe(url) {
    if (!url) return;
    const frame = document.createElement("iframe");
    frame.style.display = "none";
    frame.src = url;
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 3000);
  }

  function openInChrome() {
    if (!httpsUrl) return;
    try {
      const u = new URL(httpsUrl);
      const path = `${u.host}${u.pathname}${u.search}`;
      const fallback = encodeURIComponent(window.location.href);
      tryNavigate(
        `intent://${path}#Intent;scheme=https;package=com.android.chrome;` +
          `action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;` +
          `S.browser_fallback_url=${fallback};end`
      );
    } catch {
      tryNavigate(window.location.href);
    }
  }

  function launchApp() {
    if (!isAndroid) {
      if (httpsUrl) tryNavigate(httpsUrl);
      return;
    }
    let launched = false;
    if (intentUrl.indexOf("intent://") === 0) {
      launched = true;
      tryIframe(intentUrl);
      tryNavigate(intentUrl);
    }
    if (androidAppUrl.indexOf("android-app://") === 0) {
      setTimeout(() => {
        if (document.visibilityState !== "hidden") tryNavigate(androidAppUrl);
      }, 350);
    }
    if (!launched && playStoreUrl) {
      tryNavigate(playStoreUrl);
    }
  }

  function init() {
    const hint = $("inapp-hint");
    const settingsHint = $("settings-hint");
    const chromeBtn = $("open-chrome");
    const appBtn = $("open-app");
    const webBtn = $("open-web");
    const installBtn = $("install-app");

    show(hint, inAppBrowser && isAndroid);
    show(chromeBtn, inAppBrowser && isAndroid);
    show(settingsHint, isAndroid && !inAppBrowser);
    show(installBtn, isAndroid && !!playStoreUrl);

    if (chromeBtn) chromeBtn.onclick = (e) => { e.preventDefault(); openInChrome(); };
    if (appBtn) appBtn.onclick = (e) => { e.preventDefault(); launchApp(); };
    if (webBtn) webBtn.onclick = (e) => { e.preventDefault(); tryNavigate(httpsUrl); };
    if (installBtn) installBtn.onclick = (e) => { e.preventDefault(); tryNavigate(playStoreUrl); };

    if (isIOS && appBtn) {
      appBtn.textContent = "Open 1xBet in Safari";
    }

    // Android + real browser: try app immediately (no https fallback — that was opening the browser).
    if (isAndroid && !inAppBrowser && intentUrl.indexOf("intent://") === 0) {
      setTimeout(launchApp, 80);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();