// ==UserScript==
// @name         NFL Fantasy Live Game HUD — Stream Injector
// @namespace    https://github.com/Sunkarr/NFL-Fantasy-Live-Game-HUD
// @version      1.0.0
// @description  Injects an Ultra-Slim 68px NFL Fantasy Live Top Bar directly above any NFL livestream (DAZN, RTL+, YouTube TV, NFL.com).
// @author       NFL Fantasy Live Game HUD
// @match        https://www.dazn.com/*
// @match        https://plus.rtl.de/*
// @match        https://tv.youtube.com/*
// @match        https://www.nfl.com/*
// @match        https://www.espn.com/*
// @match        https://www.twitch.tv/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    const HUD_SERVER_URL = "http://localhost:8080/overlay";
    const FRAME_ID = "nfl-fantasy-hud-injected-frame";

    function injectHUD() {
        if (document.getElementById(FRAME_ID)) return;

        const iframe = document.createElement("iframe");
        iframe.id = FRAME_ID;
        iframe.src = HUD_SERVER_URL;
        
        // Broadcast HUD styling
        Object.assign(iframe.style, {
            position: "fixed",
            top: "0px",
            left: "0px",
            width: "100vw",
            height: "72px",
            border: "none",
            zIndex: "2147483647",
            pointerEvents: "none", // Let video player controls pass through
            background: "transparent",
            overflow: "hidden"
        });

        iframe.setAttribute("allow", "autoplay; encrypted-media");
        document.body.appendChild(iframe);
        console.log("[NFL HUD] Injected Live Game HUD bar successfully.");
    }

    // Toggle HUD with Ctrl+Shift+H
    window.addEventListener("keydown", (e) => {
        if (e.ctrlKey && e.shiftKey && (e.key === "H" || e.key === "h")) {
            const frame = document.getElementById(FRAME_ID);
            if (frame) {
                frame.style.display = (frame.style.display === "none") ? "block" : "none";
            }
        }
    });

    // Run injection once DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", injectHUD);
    } else {
        injectHUD();
    }
})();
