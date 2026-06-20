/**
 * 1xBet app opener — launches the installed app (never Play Store).
 */
(function () {
  const data = window.ONEXBET_OPEN || {};
  const httpsUrl = data.https || "";
  const intentUrl = data.intent || "";
  const androidAppUrl = data.android_app || "";

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
    // 1) android-app:// — opens installed app directly (no Play Store redirect)
    if (androidAppUrl.indexOf("android-app://") === 0) {
      tryNavigate(androidAppUrl);
    }
    // 2) intent without package — system picks 1xBet if it handles 1xbet.co.ke
    setTimeout(() => {
      if (document.visibilityState !== "hidden" && intentUrl.indexOf("intent://") === 0) {
        tryIframe(intentUrl);
        tryNavigate(intentUrl);
      }
    }, 400);
  }

  function init() {
    const hint = $("inapp-hint");
    const settingsHint = $("settings-hint");
    const chromeBtn = $("open-chrome");
    const appBtn = $("open-app");
    const webBtn = $("open-web");

    show(hint, inAppBrowser && isAndroid);
    show(chromeBtn, inAppBrowser && isAndroid);
    show(settingsHint, isAndroid);

    if (chromeBtn) chromeBtn.onclick = (e) => { e.preventDefault(); openInChrome(); };
    if (appBtn) appBtn.onclick = (e) => { e.preventDefault(); launchApp(); };
    if (webBtn) webBtn.onclick = (e) => { e.preventDefault(); tryNavigate(httpsUrl); };

    if (isIOS && appBtn) {
      appBtn.textContent = "Open 1xBet in Safari";
    }

    if (isAndroid && !inAppBrowser) {
      setTimeout(launchApp, 80);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();