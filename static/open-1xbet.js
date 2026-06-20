/**
 * 1xBet app opener — requires a user tap (Telegram/in-app browsers block auto intent redirects).
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
      const fallback = encodeURIComponent(httpsUrl);
      tryNavigate(
        `intent://${path}#Intent;scheme=https;package=com.android.chrome;` +
          `action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;` +
          `S.browser_fallback_url=${fallback};end`
      );
    } catch {
      tryNavigate(httpsUrl);
    }
  }

  function openApp() {
    if (!isAndroid) {
      tryNavigate(httpsUrl);
      return;
    }
    if (intentUrl.indexOf("intent://") === 0) {
      tryIframe(intentUrl);
      tryNavigate(intentUrl);
    }
    if (androidAppUrl.indexOf("android-app://") === 0) {
      setTimeout(() => {
        if (document.visibilityState !== "hidden") {
          tryNavigate(androidAppUrl);
        }
      }, 400);
    }
    setTimeout(() => {
      if (document.visibilityState !== "hidden") {
        tryNavigate(httpsUrl);
      }
    }, 1800);
  }

  function init() {
    const hint = $("inapp-hint");
    const chromeBtn = $("open-chrome");
    const appBtn = $("open-app");
    const webBtn = $("open-web");
    const installBtn = $("install-app");

    show(hint, inAppBrowser && isAndroid);
    show(chromeBtn, inAppBrowser && isAndroid);
    show(installBtn, isAndroid && !!playStoreUrl);

    if (chromeBtn) chromeBtn.onclick = (e) => { e.preventDefault(); openInChrome(); };
    if (appBtn) appBtn.onclick = (e) => { e.preventDefault(); openApp(); };
    if (webBtn) webBtn.onclick = (e) => { e.preventDefault(); tryNavigate(httpsUrl); };
    if (installBtn) installBtn.onclick = (e) => { e.preventDefault(); tryNavigate(playStoreUrl); };

    if (isIOS) {
      if (appBtn) appBtn.textContent = "Open 1xBet in Safari";
    }

    // Auto-open only outside in-app browsers (Chrome mobile supports intent on user-less nav sometimes).
    if (isAndroid && !inAppBrowser && intentUrl.indexOf("intent://") === 0) {
      setTimeout(openApp, 120);
    } else if (!isAndroid && httpsUrl) {
      setTimeout(() => tryNavigate(httpsUrl), 120);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();