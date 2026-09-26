// One-Click Bookmarklet for NFL Fantasy Live Game HUD
// Drag to bookmarks bar or create a new bookmark with this URL:

javascript:(function(){
    var existing = document.getElementById('nfl-hud-overlay-frame');
    if (existing) {
        existing.remove();
        return;
    }
    var iframe = document.createElement('iframe');
    iframe.id = 'nfl-hud-overlay-frame';
    iframe.src = 'http://localhost:8080/overlay';
    iframe.style.position = 'fixed';
    iframe.style.top = '0px';
    iframe.style.left = '0px';
    iframe.style.width = '100vw';
    iframe.style.height = '72px';
    iframe.style.border = 'none';
    iframe.style.zIndex = '2147483647';
    iframe.style.pointerEvents = 'none';
    iframe.style.background = 'transparent';
    iframe.allow = 'autoplay';
    document.body.appendChild(iframe);
})();
