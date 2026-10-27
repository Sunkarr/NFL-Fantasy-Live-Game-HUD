/**
 * NFL Fantasy Live Game HUD — Client Engine
 * Ultra-Slim Top Bar Realtime Controller
 * (Flicker-Free Translucent Glassmorphism, In-Place DOM Diffing, Glitch-Free Conveyor Belt, Prominent Highlights & Sound FX)
 * 
 * Global Animation Speed presets:
 * - Slow:   20s cycle (MVP 20s, Highlight 20s, Step shift 20s, Ticker 18px/s)
 * - Normal: 10s cycle (MVP 10s, Highlight 10s, Step shift 10s, Ticker 35px/s)
 * - Fast:    5s cycle (MVP 5s,  Highlight 5s,  Step shift 5s,  Ticker 65px/s)
 */

class NFLGameHUD {
  constructor() {
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 50;
    this.reconnectDelay = 2000;
    
    this.state = null;
    this.highlightQueue = [];
    this.currentHighlight = null;
    this.highlightTimer = null;
    
    // Position MVPs (QB, RB, WR, TE, DEF, K) Idle Rotation
    this.idleSpotlights = [];
    this.currentSpotlightIndex = 0;
    this.idleTimer = null;
    this.idleIntervalMs = 10000; // 10s default per position MVP
    
    this.prevScores = new Map(); // roster_id -> score

    // Multi-Matchup Display Engine
    this.displayMode = 'auto'; // 'auto' | 'ticker' | 'step'
    this.displaySpeed = 'normal'; // 'normal' | 'fast' | 'slow'
    this.stepInterval = 10000; // 10s default between step shifts
    this.tickerSpeed = 35;     // px/sec for continuous marquee
    this.stepIndex = 0;
    this.stepTimer = null;
    this.tickerAnimationId = null;
    this.tickerOffset = 0;
    this.lastTimestamp = null;
    this.isPaused = false;

    // Track layout structure to prevent unnecessary DOM recreation & flicker
    this.renderedMode = null;
    this.renderedMatchupCount = 0;
    this.renderedWeek = null;
    this.cachedMatchups = [];

    // Audio & Sound FX System
    // Preloaded Media Cache to eliminate pop-in delay
    this.preloadedMedia = new Set();

    this.soundEnabled = localStorage.getItem('nfl_hud_sound_enabled') === 'true';
    this.soundTheme = localStorage.getItem('nfl_hud_sound_theme') || 'fox_horn';

    // Highlight & Live Injury Update Toggles and Queues
    this.highlightsEnabled = localStorage.getItem('nfl_hud_highlights_enabled') !== 'false';
    this.injuriesEnabled = localStorage.getItem('nfl_hud_injuries_enabled') !== 'false';
    this.injurySoundEnabled = localStorage.getItem('nfl_hud_injury_sound_enabled') !== 'false';
    this.injurySoundTheme = localStorage.getItem('nfl_hud_injury_sound_theme') || 'whistle_blow';
    this.injuryQueue = [];
    this.currentInjury = null;
    this.injuryTimer = null;
    this.audioCtx = null;
    this.toastTimer = null;

    // Visual Theme / Design Variant: clean_minimal | slate_nordic | stealth_oled | classic_glass
    this.theme = localStorage.getItem('nfl_hud_theme') || 'clean_minimal';

    // DOM Elements
    this.dom = {
      topBar: document.getElementById('hud-top-bar'),
      weekTag: document.getElementById('hud-week-tag'),
      soundToggleBtn: document.getElementById('hud-sound-toggle-btn'),
      soundIcon: document.getElementById('sound-icon'),
      matchupsContainer: document.getElementById('hud-matchups-container') || document.getElementById('matchups-container'),
      highlightContainer: document.getElementById('hud-highlight-container') || document.getElementById('highlight-container'),
      toast: document.getElementById('hud-toast')
    };

    this.init();
  }

  init() {
    this.initSoundControls();
    this.initKeyboardShortcuts();
    this.connectWebSocket();
    this.fetchInitialState();

    // Pause conveyor belt / ticker animations on hover so users can inspect
    if (this.dom.matchupsContainer) {
      this.dom.matchupsContainer.addEventListener('mouseenter', () => { this.isPaused = true; });
      this.dom.matchupsContainer.addEventListener('mouseleave', () => { this.isPaused = false; });
    }
  }

  // =========================================================================
  // WebSocket & Real-Time Sync
  // =========================================================================
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.ws.send(JSON.stringify({ type: 'REQUEST_STATE' }));
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleSocketMessage(msg);
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };

    this.ws.onclose = () => {
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.warn('WebSocket encountered error:', err);
    };
  }

  scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    this.reconnectAttempts++;
    const delay = Math.min(this.reconnectDelay * Math.pow(1.3, this.reconnectAttempts), 15000);
    setTimeout(() => this.connectWebSocket(), delay);
  }

  async fetchInitialState() {
    try {
      const res = await fetch('/api/state');
      if (res.ok) {
        const data = await res.json();
        this.renderState(data);
      }
    } catch (e) {
      console.warn('Initial state fetch failed:', e);
    }
  }

  handleSocketMessage(msg) {
    switch (msg.type) {
      case 'INITIAL_STATE':
      case 'UPDATE_MATCHUPS':
        this.renderState(msg.state);
        break;
      case 'PUSH_HIGHLIGHT':
        this.enqueueHighlight(msg.highlight);
        break;
      case 'PUSH_INJURY':
        this.enqueueInjury(msg.injury);
        break;
      case 'UPDATE_DISPLAY_SETTINGS':
        this.applyDisplaySettings(msg.settings);
        break;
      case 'PONG':
        break;
    }
  }

  applyDisplaySettings(settings) {
    if (!settings) return;
    let modeChanged = false;
    let speedChanged = false;

    if (settings.mode) {
      const newMode = settings.mode === 'paged' ? 'step' : settings.mode;
      if (newMode !== this.displayMode) {
        this.displayMode = newMode;
        modeChanged = true;
      }
    }
    if (settings.speed) {
      if (settings.speed !== this.displaySpeed) {
        speedChanged = true;
      }
      this.displaySpeed = settings.speed;

      // Slow: 20s, Normal: 10s, Fast: 5s
      if (settings.speed === 'fast') {
        this.stepInterval = 5000;
        this.tickerSpeed = 65;
        this.idleIntervalMs = 5000;
      } else if (settings.speed === 'slow') {
        this.stepInterval = 20000;
        this.tickerSpeed = 18;
        this.idleIntervalMs = 20000;
      } else { // normal
        this.stepInterval = 10000;
        this.tickerSpeed = 35;
        this.idleIntervalMs = 10000;
      }
    }
    if (settings.step_interval_seconds) {
      this.stepInterval = settings.step_interval_seconds * 1000;
    }
    if (settings.ticker_speed) {
      this.tickerSpeed = settings.ticker_speed;
    }
    
    // Sync sound if server explicitly passed it
    if (typeof settings.sound_enabled === 'boolean') {
      if (this.soundEnabled !== settings.sound_enabled) {
        this.soundEnabled = settings.sound_enabled;
        localStorage.setItem('nfl_hud_sound_enabled', this.soundEnabled ? 'true' : 'false');
        this.updateSoundUI();
      }
    }
    if (settings.sound_theme) {
      this.soundTheme = settings.sound_theme;
      localStorage.setItem('nfl_hud_sound_theme', this.soundTheme);
    }
    if (typeof settings.highlights_enabled === 'boolean') {
      this.highlightsEnabled = settings.highlights_enabled;
      localStorage.setItem('nfl_hud_highlights_enabled', this.highlightsEnabled ? 'true' : 'false');
    }
    if (typeof settings.injuries_enabled === 'boolean') {
      this.injuriesEnabled = settings.injuries_enabled;
      localStorage.setItem('nfl_hud_injuries_enabled', this.injuriesEnabled ? 'true' : 'false');
    }
    if (typeof settings.injury_sound_enabled === 'boolean') {
      this.injurySoundEnabled = settings.injury_sound_enabled;
      localStorage.setItem('nfl_hud_injury_sound_enabled', this.injurySoundEnabled ? 'true' : 'false');
    }
    if (settings.injury_sound_theme) {
      this.injurySoundTheme = settings.injury_sound_theme;
      localStorage.setItem('nfl_hud_injury_sound_theme', this.injurySoundTheme);
    }
    
    if (speedChanged) {
      this.restartIdleTimer();
      if (this.renderedMode === 'step' && this.stepTimer) {
        this.resetMatchupLayout(this.cachedMatchups);
      }
    }

    if (modeChanged && this.state && this.state.matchups) {
      this.resetMatchupLayout(this.state.matchups);
    }
  }

  getSpeedDurationSeconds() {
    if (this.displaySpeed === 'slow') return 20;
    if (this.displaySpeed === 'fast') return 5;
    return 10;
  }

  // =========================================================================
  // State & Matchups Rendering (Flicker-Free In-Place Updates)
  // =========================================================================
  preloadMedia(state) {
    if (!state) return;
    const urls = [];
    if (Array.isArray(state.matchups)) {
      state.matchups.forEach(m => {
        if (m.team_a && m.team_a.avatar_url) urls.push(m.team_a.avatar_url);
        if (m.team_b && m.team_b.avatar_url) urls.push(m.team_b.avatar_url);
      });
    }
    if (Array.isArray(state.idle_spotlights)) {
      state.idle_spotlights.forEach(s => {
        if (s && s.headshot_url) urls.push(s.headshot_url);
      });
    }
    urls.forEach(url => {
      if (url && !this.preloadedMedia.has(url)) {
        this.preloadedMedia.add(url);
        const img = new Image();
        img.src = url;
      }
    });
  }

  handleTeamAvatarError(img) {
    if (img && !img.dataset.fallbackApplied) {
      img.dataset.fallbackApplied = 'true';
      img.src = 'https://sleepercdn.com/images/v2/icons/player_default.webp';
    }
  }

  renderState(state) {
    if (!state) return;
    this.state = state;
    this.preloadMedia(state);

    if (state.display_settings) {
      this.applyDisplaySettings(state.display_settings);
    }

    // 1. Update Week Tag (Only if changed)
    if (state.week && this.renderedWeek !== state.week) {
      this.renderedWeek = state.week;
      if (this.dom.weekTag) {
        this.dom.weekTag.textContent = `WK ${state.week}`;
      }
    }

    // 2. Update Position MVPs list (filter out zero FPTS players)
    const incomingMVPs = state.idle_spotlights || (state.idle_spotlight ? [state.idle_spotlight] : []);
    this.idleSpotlights = (incomingMVPs || []).filter(p => p && Math.round((Number(p.points) || 0) * 100) !== 0);

    // 3. Matchups Rendering
    const matchups = state.matchups || [];
    this.cachedMatchups = matchups;
    const matchupCount = matchups.length;

    // Determine target mode
    let targetMode = this.displayMode;
    if (targetMode === 'auto') {
      targetMode = matchupCount <= 3 ? 'static' : 'step';
    }

    const structureChanged = (
      this.renderedMode !== targetMode ||
      this.renderedMatchupCount !== matchupCount
    );

    if (structureChanged) {
      this.resetMatchupLayout(matchups, targetMode);
    } else {
      this.updateExistingCardsInPlace(matchups);
    }

    // 4. Highlight & Position MVP Rotation
    if (!this.currentHighlight) {
      this.startIdleSpotlightCycle();
    }
  }

  resetMatchupLayout(matchups, targetMode) {
    if (!targetMode) {
      targetMode = this.displayMode;
      if (targetMode === 'auto') {
        targetMode = matchups.length <= 3 ? 'static' : 'step';
      }
    }

    if (this.stepTimer) {
      clearInterval(this.stepTimer);
      this.stepTimer = null;
    }
    if (this.tickerAnimationId) {
      cancelAnimationFrame(this.tickerAnimationId);
      this.tickerAnimationId = null;
    }

    this.renderedMode = targetMode;
    this.renderedMatchupCount = matchups.length;

    if (targetMode === 'static' || matchups.length <= 3) {
      this.renderStaticMatchups(matchups);
    } else if (targetMode === 'ticker') {
      this.renderContinuousTicker(matchups);
    } else {
      this.renderStepShiftMatchups(matchups);
    }
  }

  updateExistingCardsInPlace(matchups) {
    if (!matchups || matchups.length === 0) return;
    const mById = new Map();
    matchups.forEach(m => mById.set(m.matchup_id, m));

    const cards = this.dom.matchupsContainer.querySelectorAll('.matchup-card');
    cards.forEach((card) => {
      const mid = parseInt(card.dataset.matchupId, 10);
      const m = mById.get(mid);
      if (!m) return;

      const teamA = m.team_a;
      const teamB = m.team_b;
      const colorA = teamA && teamA.color_accent ? teamA.color_accent : '#00f0ff';
      const colorB = teamB && teamB.color_accent ? teamB.color_accent : '#ff00aa';

      const scoreA = teamA ? teamA.points : 0;
      const scoreB = teamB ? teamB.points : 0;
      const totalScore = scoreA + scoreB;
      const pctScoreA = totalScore > 0 ? ((scoreA / totalScore) * 100).toFixed(1) : 50;
      const pctScoreB = (100 - pctScoreA).toFixed(1);

      // Minutes calculation (0 to 50% for each team, meeting at center)
      const minPlayedA = teamA && teamA.minutes_played ? teamA.minutes_played : 0;
      const totalMinA = teamA && teamA.total_minutes ? teamA.total_minutes : 540;
      const minPctA = totalMinA > 0 ? (minPlayedA / totalMinA) : 0;
      const widthMinA = (Math.min(1.0, Math.max(0.0, minPctA)) * 50).toFixed(1);

      const minPlayedB = teamB && teamB.minutes_played ? teamB.minutes_played : 0;
      const totalMinB = teamB && teamB.total_minutes ? teamB.total_minutes : 540;
      const minPctB = totalMinB > 0 ? (minPlayedB / totalMinB) : 0;
      const widthMinB = (Math.min(1.0, Math.max(0.0, minPctB)) * 50).toFixed(1);

      card.style.setProperty('--card-color-a', colorA);
      card.style.setProperty('--card-color-b', colorB);

      const vsEl = card.querySelector('.vs-divider');
      if (vsEl) {
        vsEl.textContent = '·';
      }

      // Update team avatars in place if changed
      const avatarElA = card.querySelector('.avatar-a');
      const avatarElB = card.querySelector('.avatar-b');
      if (avatarElA && teamA && teamA.avatar_url && avatarElA.src !== teamA.avatar_url) {
        avatarElA.src = teamA.avatar_url;
      }
      if (avatarElB && teamB && teamB.avatar_url && avatarElB.src !== teamB.avatar_url) {
        avatarElB.src = teamB.avatar_url;
      }

      const scoreElA = card.querySelector('.score-a');
      const scoreElB = card.querySelector('.score-b');
      const leaderRosterId = m.leader_roster_id;
      const isTied = Math.abs(scoreA - scoreB) < 0.05;

      if (scoreElA) {
        const prevText = scoreElA.textContent.trim();
        const newText = scoreA.toFixed(1);
        if (prevText !== newText) {
          scoreElA.textContent = newText;
          if (this.checkScoreFlash(teamA ? teamA.roster_id : null, scoreA)) {
            scoreElA.classList.remove('score-flash');
            void scoreElA.offsetWidth;
            scoreElA.classList.add('score-flash');
          }
        }
        if (!isTied && leaderRosterId && leaderRosterId === (teamA && teamA.roster_id)) {
          scoreElA.classList.add('leading');
        } else {
          scoreElA.classList.remove('leading');
        }
      }

      if (scoreElB) {
        const prevText = scoreElB.textContent.trim();
        const newText = scoreB.toFixed(1);
        if (prevText !== newText) {
          scoreElB.textContent = newText;
          if (this.checkScoreFlash(teamB ? teamB.roster_id : null, scoreB)) {
            scoreElB.classList.remove('score-flash');
            void scoreElB.offsetWidth;
            scoreElB.classList.add('score-flash');
          }
        }
        if (!isTied && leaderRosterId && leaderRosterId === (teamB && teamB.roster_id)) {
          scoreElB.classList.add('leading');
        } else {
          scoreElB.classList.remove('leading');
        }
      }

      // Update Red Zone indicators
      const rzSlotA = card.querySelector('.rz-slot-a');
      const rzSlotB = card.querySelector('.rz-slot-b');
      if (rzSlotA) rzSlotA.innerHTML = this.renderRedZoneIndicator(teamA, colorA);
      if (rzSlotB) rzSlotB.innerHTML = this.renderRedZoneIndicator(teamB, colorB);

      // Update Bar 1: Score distribution
      const barA = card.querySelector('.score-bar-left');
      const barB = card.querySelector('.score-bar-right');
      if (barA) barA.style.width = `${pctScoreA}%`;
      if (barB) barB.style.width = `${pctScoreB}%`;

      // Update Bar 2: Minutes played (meeting at center)
      const minBarA = card.querySelector('.minutes-bar-left');
      const minBarB = card.querySelector('.minutes-bar-right');
      if (minBarA) minBarA.style.width = `${widthMinA}%`;
      if (minBarB) minBarB.style.width = `${widthMinB}%`;
      const minBar = card.querySelector('.minutes-bar');
      if (minBar) {
        minBar.title = `Game Time: ${Math.round(minPlayedA)}m / ${totalMinA}m (${Math.round(minPctA * 100)}%) vs ${Math.round(minPlayedB)}m / ${totalMinB}m (${Math.round(minPctB * 100)}%)`;
      }
    });
  }

  // 1. Static 3-Matchup Display (Default for <= 3 matchups)
  renderStaticMatchups(matchups) {
    const container = this.dom.matchupsContainer;
    container.className = 'matchups-container static-mode';
    container.innerHTML = '';

    matchups.forEach((m) => {
      const card = this.createMatchupCardElement(m);
      container.appendChild(card);
    });
  }

  // 2. Step-by-Step Shift Mode ("Conveyor Belt Step Shift")
  renderStepShiftMatchups(matchups) {
    const container = this.dom.matchupsContainer;
    container.className = 'matchups-container step-mode';
    container.innerHTML = '';

    const count = matchups.length;
    if (count <= 3) {
      this.renderStaticMatchups(matchups);
      return;
    }

    const track = document.createElement('div');
    track.className = 'step-track';
    container.appendChild(track);

    let isShifting = false;

    const populateTrack = (startIdx) => {
      track.innerHTML = '';
      track.classList.remove('sliding');
      track.style.transform = 'translate3d(0, 0, 0)';

      for (let i = 0; i < 4; i++) {
        const itemIdx = (startIdx + i) % count;
        const card = this.createMatchupCardElement(matchups[itemIdx]);
        card.classList.add('step-card');
        track.appendChild(card);
      }
    };

    populateTrack(this.stepIndex);

    this.stepTimer = setInterval(() => {
      if (this.isPaused || isShifting) return;
      isShifting = true;

      const firstCard = track.children[0];
      const cardWidth = firstCard ? firstCard.getBoundingClientRect().width : 0;
      const gap = 12;
      const shiftDistance = cardWidth + gap;

      track.classList.add('sliding');
      track.style.transform = `translate3d(-${shiftDistance}px, 0, 0)`;

      const onTransitionEnd = () => {
        track.removeEventListener('transitionend', onTransitionEnd);
        this.stepIndex = (this.stepIndex + 1) % count;
        populateTrack(this.stepIndex);
        isShifting = false;
      };

      track.addEventListener('transitionend', onTransitionEnd);
    }, this.stepInterval);
  }

  // 3. Ticker / Continuous Rolling Marquee Mode
  renderContinuousTicker(matchups) {
    const container = this.dom.matchupsContainer;
    container.className = 'matchups-container ticker-mode';
    container.innerHTML = '';

    const count = matchups.length;
    const track = document.createElement('div');
    track.className = 'ticker-track';
    container.appendChild(track);

    const repetitions = count < 6 ? 4 : 2;
    for (let r = 0; r < repetitions; r++) {
      matchups.forEach((m) => {
        const card = this.createMatchupCardElement(m);
        card.classList.add('ticker-card');
        track.appendChild(card);
      });
    }

    this.tickerOffset = 0;
    this.lastTimestamp = performance.now();

    const animate = (now) => {
      if (!this.lastTimestamp) this.lastTimestamp = now;
      const delta = (now - this.lastTimestamp) / 1000;
      this.lastTimestamp = now;

      if (!this.isPaused) {
        this.tickerOffset -= this.tickerSpeed * delta;
        const singleSetWidth = track.scrollWidth / repetitions;
        if (Math.abs(this.tickerOffset) >= singleSetWidth) {
          this.tickerOffset += singleSetWidth;
        }
        track.style.transform = `translate3d(${this.tickerOffset}px, 0, 0)`;
      }

      this.tickerAnimationId = requestAnimationFrame(animate);
    };

    this.tickerAnimationId = requestAnimationFrame(animate);
  }

  // Helper to create single matchup card DOM with glowing manager colors & dual progress bars
  createMatchupCardElement(m) {
    const card = document.createElement('div');
    card.className = 'matchup-card';
    card.dataset.matchupId = m.matchup_id;
    
    const teamA = m.team_a;
    const teamB = m.team_b;

    // Distinct glowy accent colors
    const colorA = teamA && teamA.color_accent ? teamA.color_accent : '#00f0ff';
    const colorB = teamB && teamB.color_accent ? teamB.color_accent : '#ff00aa';

    const scoreA = teamA ? teamA.points : 0;
    const scoreB = teamB ? teamB.points : 0;
    const totalScore = scoreA + scoreB;
    const pctScoreA = totalScore > 0 ? ((scoreA / totalScore) * 100).toFixed(1) : 50;
    const pctScoreB = (100 - pctScoreA).toFixed(1);

    // Minutes calculation (0 to 50% for each team, meeting at center)
    const minPlayedA = teamA && teamA.minutes_played ? teamA.minutes_played : 0;
    const totalMinA = teamA && teamA.total_minutes ? teamA.total_minutes : 540;
    const minPctA = totalMinA > 0 ? (minPlayedA / totalMinA) : 0;
    const widthMinA = (Math.min(1.0, Math.max(0.0, minPctA)) * 50).toFixed(1);

    const minPlayedB = teamB && teamB.minutes_played ? teamB.minutes_played : 0;
    const totalMinB = teamB && teamB.total_minutes ? teamB.total_minutes : 540;
    const minPctB = totalMinB > 0 ? (minPlayedB / totalMinB) : 0;
    const widthMinB = (Math.min(1.0, Math.max(0.0, minPctB)) * 50).toFixed(1);

    const flashA = this.checkScoreFlash(teamA ? teamA.roster_id : null, scoreA);
    const flashB = this.checkScoreFlash(teamB ? teamB.roster_id : null, scoreB);

    const leaderRosterId = m.leader_roster_id;
    const isTied = Math.abs(scoreA - scoreB) < 0.05;
    const isLeadingA = !isTied && leaderRosterId && leaderRosterId === (teamA && teamA.roster_id);
    const isLeadingB = !isTied && leaderRosterId && leaderRosterId === (teamB && teamB.roster_id);

    const rzHtmlA = this.renderRedZoneIndicator(teamA, colorA);
    const rzHtmlB = this.renderRedZoneIndicator(teamB, colorB);

    card.style.setProperty('--card-color-a', colorA);
    card.style.setProperty('--card-color-b', colorB);

    card.innerHTML = `
      <div class="matchup-teams-row">
        <div class="team-side left">
          <img class="team-avatar avatar-a" src="${teamA ? teamA.avatar_url : ''}" alt="${teamA ? teamA.manager_name : ''}" title="${teamA ? teamA.manager_name : ''}" style="border-color: ${colorA}; --team-color: ${colorA};" onerror="window.hud && window.hud.handleTeamAvatarError ? window.hud.handleTeamAvatarError(this) : (this.src='https://sleepercdn.com/images/v2/icons/player_default.webp')" />
          <div class="rz-slot-a">${rzHtmlA}</div>
        </div>

        <div class="matchup-center-scores">
          <span class="team-score score-a ${isLeadingA ? 'leading' : ''} ${flashA ? 'score-flash' : ''}">
            ${scoreA.toFixed(1)}
          </span>
          <span class="vs-divider">·</span>
          <span class="team-score score-b ${isLeadingB ? 'leading' : ''} ${flashB ? 'score-flash' : ''}">
            ${scoreB.toFixed(1)}
          </span>
        </div>

        <div class="team-side right">
          <div class="rz-slot-b">${rzHtmlB}</div>
          <img class="team-avatar avatar-b" src="${teamB ? teamB.avatar_url : ''}" alt="${teamB ? teamB.manager_name : ''}" title="${teamB ? teamB.manager_name : ''}" style="border-color: ${colorB}; --team-color: ${colorB};" onerror="window.hud && window.hud.handleTeamAvatarError ? window.hud.handleTeamAvatarError(this) : (this.src='https://sleepercdn.com/images/v2/icons/player_default.webp')" />
        </div>
      </div>

      <div class="matchup-bars-group">
        <div class="matchup-bar score-bar" title="Points: ${scoreA.toFixed(1)} vs ${scoreB.toFixed(1)}">
          <div class="score-bar-left" style="width: ${pctScoreA}%; background: ${colorA}; --team-color: ${colorA};"></div>
          <div class="score-bar-right" style="width: ${pctScoreB}%; background: ${colorB}; --team-color: ${colorB};"></div>
        </div>

        <div class="matchup-bar minutes-bar" title="Game Time: ${Math.round(minPlayedA)}m / ${totalMinA}m (${Math.round(minPctA * 100)}%) vs ${Math.round(minPlayedB)}m / ${totalMinB}m (${Math.round(minPctB * 100)}%)">
          <div class="minutes-bar-track">
            <div class="minutes-bar-left" style="width: ${widthMinA}%;"></div>
            <div class="minutes-center-line"></div>
            <div class="minutes-bar-right" style="width: ${widthMinB}%;"></div>
          </div>
        </div>
      </div>
    `;

    return card;
  }

  // Render Red Zone alert indicator: 1-3 glowing dots or '3+' badge in manager accent color
  renderRedZoneIndicator(team, color) {
    if (!team || !team.redzone_count || team.redzone_count <= 0) {
      return '';
    }
    const count = team.redzone_count;
    const players = (team.redzone_players || []).join(', ');
    const titleText = `Red Zone: ${players || `${count} player${count > 1 ? 's' : ''}`}`;

    if (count <= 3) {
      let dotsHtml = '';
      for (let i = 0; i < count; i++) {
        dotsHtml += `<span class="rz-dot" style="background: ${color}; --rz-color: ${color};"></span>`;
      }
      return `<div class="rz-alert-container" title="${titleText}">${dotsHtml}</div>`;
    } else {
      const bg = this.hexToRgba(color, 0.22);
      const border = this.hexToRgba(color, 0.7);
      return `<div class="rz-alert-container" title="${titleText}"><span class="rz-badge-more" style="background: ${bg}; color: ${color}; border: 1px solid ${border}; --rz-color: ${color};">3+</span></div>`;
    }
  }

  checkScoreFlash(rosterId, currentScore) {
    if (!rosterId) return false;
    const prev = this.prevScores.get(rosterId);
    this.prevScores.set(rosterId, currentScore);
    return prev !== undefined && currentScore > prev;
  }

  // =========================================================================
  // Position MVP Cycle & Prominent Highlights Engine
  // =========================================================================
  startIdleSpotlightCycle(forceImmediate = false) {
    if (this.currentHighlight || this.currentInjury) return;

    const activeMVPs = (this.idleSpotlights || []).filter(p => p && Math.round((Number(p.points) || 0) * 100) !== 0);

    if (activeMVPs.length === 0) {
      this.stopIdleSpotlightCycle();
      if (this.dom.highlightContainer) {
        this.dom.highlightContainer.innerHTML = `
          <div class="spotlight-pill mvp-pill pregame-pill">
            <div class="spotlight-avatar-wrap" style="display: flex; align-items: center; justify-content: center; font-size: 16px; background: rgba(255,255,255,0.06); border-radius: 50%;">
              🏈
            </div>
            <div class="spotlight-info">
              <span class="spotlight-top-tag" style="color: var(--color-text-dim); font-weight: 700;">PREGAME</span>
              <span class="spotlight-player-name" style="color: #cbd5e1; font-size: 13px; font-weight: 600;">Awaiting Kickoff</span>
            </div>
            <div class="spotlight-score-badge">
              <span class="spotlight-pts-value" style="color: var(--color-text-dim); font-weight: 600;">
                <span class="pts-number">0.0</span><span class="pts-sub" style="font-size: 9px; color: var(--color-text-dim); font-weight: 600;">FPTS</span>
              </span>
            </div>
          </div>
        `;
      }
      return;
    }

    const hasMvpCard = this.dom.highlightContainer && !!this.dom.highlightContainer.querySelector('.mvp-pill');

    if (!hasMvpCard || forceImmediate) {
      this.stopIdleSpotlightCycle();
      if (this.currentSpotlightIndex >= activeMVPs.length) {
        this.currentSpotlightIndex = 0;
      }
      this.renderIdleSpotlight(activeMVPs[this.currentSpotlightIndex]);
    }

    if (this.idleTimer) return;

    this.idleTimer = setInterval(() => {
      const currentList = (this.idleSpotlights || []).filter(p => p && Math.round((Number(p.points) || 0) * 100) !== 0);
      if (!this.currentHighlight && !this.currentInjury && currentList.length > 0) {
        this.currentSpotlightIndex = (this.currentSpotlightIndex + 1) % currentList.length;
        this.renderIdleSpotlight(currentList[this.currentSpotlightIndex]);
      }
    }, this.idleIntervalMs);
  }

  restartIdleTimer() {
    this.stopIdleSpotlightCycle();
    if (!this.currentHighlight && !this.currentInjury) {
      this.startIdleSpotlightCycle();
    }
  }

  stopIdleSpotlightCycle() {
    if (this.idleTimer) {
      clearInterval(this.idleTimer);
      this.idleTimer = null;
    }
  }

  enqueueHighlight(highlight) {
    if (!this.highlightsEnabled || !highlight) return;
    this.highlightQueue.push(highlight);
    
    if (!this.currentHighlight && !this.currentInjury) {
      this.stopIdleSpotlightCycle();
      this.playNextHighlight();
    } else {
      this.updateQueueBadge();
      
      const activeCard = this.dom.highlightContainer.querySelector('.spotlight-pill.live-highlight');
      if (activeCard) {
        activeCard.classList.remove('jiggling');
        void activeCard.offsetWidth;
        activeCard.classList.add('jiggling');
      }
    }
  }

  updateQueueBadge() {
    const queueBadge = document.getElementById('spotlight-queue-badge');
    const remaining = this.highlightQueue.length;
    if (queueBadge) {
      if (remaining > 0) {
        queueBadge.textContent = `+${remaining} IN QUEUE`;
        queueBadge.style.display = 'inline-block';
      } else {
        queueBadge.style.display = 'none';
      }
    }
  }

  playNextHighlight() {
    if (!this.highlightsEnabled) {
      this.highlightQueue = [];
      this.currentHighlight = null;
      if (this.injuryQueue.length > 0) {
        this.playNextInjury();
      } else if (!this.currentInjury) {
        this.startIdleSpotlightCycle(true);
      }
      return;
    }
    if (this.highlightQueue.length === 0) {
      this.currentHighlight = null;
      if (this.injuryQueue.length > 0) {
        this.playNextInjury();
      } else if (!this.currentInjury) {
        this.startIdleSpotlightCycle(true);
      }
      return;
    }

    const hl = this.highlightQueue.shift();
    this.currentHighlight = hl;
    
    this.playNFLFanfareSound();

    const durationSec = this.getSpeedDurationSeconds();
    this.renderHighlightPill(hl, durationSec);

    const durationMs = durationSec * 1000;
    if (this.highlightTimer) clearTimeout(this.highlightTimer);
    
    this.highlightTimer = setTimeout(() => {
      this.playNextHighlight();
    }, durationMs);
  }

  getBenchPrefix(player) {
    if (!player) return '';
    const isBench = player.is_starter === false || (player.roster_slot || '').toUpperCase() === 'BENCH';
    if (!isBench) return '';
    return '<span class="bench-tag" title="Bench Player">B</span>';
  }

  formatPlayerDisplayName(name, position, nflTeam) {
    if (!name) return '';
    const pos = (position || '').toUpperCase();
    
    if (pos === 'DEF') {
      if (nflTeam && nflTeam.trim().length > 0) {
        return nflTeam.trim().toUpperCase();
      }
      const upperName = name.trim().toUpperCase();
      if (upperName.length <= 4) return upperName;
      const teamMap = {
        'MINNESOTA VIKINGS': 'MIN', 'BUFFALO BILLS': 'BUF', 'KANSAS CITY CHIEFS': 'KC',
        'SAN FRANCISCO 49ERS': 'SF', 'DALLAS COWBOYS': 'DAL', 'PHILADELPHIA EAGLES': 'PHI',
        'BALTIMORE RAVENS': 'BAL', 'DETROIT LIONS': 'DET', 'MIAMI DOLPHINS': 'MIA',
        'GREEN BAY PACKERS': 'GB', 'HOUSTON TEXANS': 'HOU', 'PITTSBURGH STEELERS': 'PIT',
        'NEW YORK JETS': 'NYJ', 'NEW YORK GIANTS': 'NYG', 'LOS ANGELES RAMS': 'LAR',
        'LOS ANGELES CHARGERS': 'LAC', 'SEATTLE SEAHAWKS': 'SEA', 'TAMPA BAY BUCCANEERS': 'TB',
        'NEW ORLEANS SAINTS': 'NO', 'ATLANTA FALCONS': 'ATL', 'CAROLINA PANTHERS': 'CAR',
        'CHICAGO BEARS': 'CHI', 'CINCINNATI BENGALS': 'CIN', 'COWBOYS': 'DAL',
        'CLEVELAND BROWNS': 'CLE', 'DENVER BRONCOS': 'DEN', 'INDIANAPOLIS COLTS': 'IND',
        'JACKSONVILLE JAGUARS': 'JAX', 'LAS VEGAS RAIDERS': 'LV', 'NEW ENGLAND PATRIOTS': 'NE',
        'ARIZONA CARDINALS': 'ARI', 'TENSEE TITANS': 'TEN', 'WASHINGTON COMMANDERS': 'WAS'
      };
      for (const [key, abbr] of Object.entries(teamMap)) {
        if (upperName.includes(key) || key.includes(upperName)) {
          return abbr;
        }
      }
      return upperName.replace(/DEFENSE|DEF/i, '').trim().substring(0, 3).toUpperCase();
    }

    const parts = name.trim().split(/\s+/);
    if (parts.length <= 1) return name;

    const firstName = parts[0];
    const initial = firstName.charAt(0).toUpperCase() + '.';
    const surname = parts.slice(1).join(' ');

    return `${initial} ${surname}`;
  }

  formatHighlightDisplayName(name, position, nflTeam) {
    return this.formatPlayerDisplayName(name, position, nflTeam);
  }

  getHighlightHeaderInfo(hl) {
    const type = (hl.highlight_type || '').toLowerCase();
    const isTD = hl.is_touchdown || type === 'touchdown';
    const isOver10 = (hl.delta_points || 0) >= 10.0;
    const flameIcon = isOver10 ? '🔥' : '';

    if (isTD) {
      return {
        emoji: '🏈' + flameIcon,
        label: 'TOUCHDOWN'
      };
    } else if (type === 'field_goal' || hl.position === 'K') {
      return {
        emoji: '🎯' + flameIcon,
        label: 'FIELD GOAL'
      };
    } else if (type === 'def_stop' || (hl.position === 'DEF' && !isTD)) {
      return {
        emoji: '🛡️' + flameIcon,
        label: 'DEF STOP'
      };
    } else {
      return {
        emoji: '⚡' + flameIcon,
        label: 'BIG PLAY'
      };
    }
  }

  getOwnerColor(event) {
    if (!event) return '#00f0ff';
    // Match against current state matchups by manager or team name
    if (this.state && this.state.matchups) {
      const targetMgr = (event.manager_name || '').toLowerCase().trim();
      const targetTeam = (event.fantasy_team_name || '').toLowerCase().trim();
      for (const m of this.state.matchups) {
        for (const t of [m.team_a, m.team_b]) {
          if (!t) continue;
          const tMgr = (t.manager_name || '').toLowerCase().trim();
          const tName = (t.team_name || '').toLowerCase().trim();
          if ((targetMgr && tMgr && tMgr === targetMgr) || (targetTeam && tName && tName === targetTeam)) {
            if (t.color_accent) return t.color_accent;
          }
        }
      }
    }
    if (event.color_accent && event.color_accent !== '#ef4444' && event.color_accent !== '#f59e0b' && event.color_accent !== '#94a3b8') {
      return event.color_accent;
    }
    return event.color_accent || (event.is_user_team ? '#00f0ff' : '#94a3b8');
  }

  renderHighlightPill(hl, durationSec = 10) {
    if (!this.dom.highlightContainer) return;

    const ownerColor = this.getOwnerColor(hl);
    const remaining = this.highlightQueue.length;
    const showQueue = remaining > 0 ? '' : 'display: none;';

    const header = this.getHighlightHeaderInfo(hl);

    this.dom.highlightContainer.innerHTML = `
      <div class="spotlight-pill live-highlight" style="border-color: ${ownerColor} !important; --hl-glow-color: ${ownerColor};">
        <div class="spotlight-avatar-wrap">
          <img class="spotlight-avatar" src="${hl.headshot_url}" alt="${hl.player_name}" style="border-color: ${ownerColor}; --team-color: ${ownerColor};" onerror="window.hud && window.hud.handleAvatarError(this, '${hl.nfl_team || ""}', ${hl.position === "DEF"})" />
          <span class="spotlight-pos-badge" style="background: rgba(0, 0, 0, 0.85); border: 1.5px solid ${ownerColor}; color: #ffffff; font-weight: 900;">${hl.position}</span>
        </div>

        <div class="spotlight-info">
          <span class="spotlight-top-tag" style="color: #ffffff; font-weight: 700;">
            ${header.emoji} ${header.label}
          </span>
          <span class="spotlight-player-name">${this.escapeHtml(this.formatPlayerDisplayName(hl.player_name, hl.position, hl.nfl_team))}</span>
        </div>

        <div class="spotlight-queue-slot">
          <span class="spotlight-queue-badge" id="spotlight-queue-badge" style="${showQueue}">+${remaining} IN QUEUE</span>
        </div>

        <div class="spotlight-score-badge">
          <span class="spotlight-pts-value" style="color: #ffffff !important; border: 1px solid ${ownerColor} !important; background: ${this.hexToRgba(ownerColor, 0.25)} !important; font-weight: 600;">
            ${this.getBenchPrefix(hl)}<span class="pts-number">+${hl.delta_points.toFixed(1)}</span><span class="pts-sub" style="color: #ffffff !important; opacity: 0.9;">FPTS</span>
          </span>
        </div>

        <div class="spotlight-timer-bar" style="background: ${ownerColor} !important; animation: timer-shrink ${durationSec}s linear forwards;"></div>
      </div>
    `;
  }

  renderIdleSpotlight(spotlight) {
    if (!this.dom.highlightContainer || !spotlight) return;

    const pts = Number(spotlight.points) || 0;
    if (Math.round(pts * 100) === 0) return;

    const isFA = spotlight.is_free_agent;
    const accentColor = spotlight.color_accent || (isFA ? '#94a3b8' : '#00f0ff');
    
    const isLeader = spotlight.rank === 1;
    const leaderCrown = isLeader ? '👑 ' : '';
    const rankPart = spotlight.rank ? `#${spotlight.rank} ` : '';
    const mgrName = spotlight.manager_name || spotlight.fantasy_team_name || (isFA ? 'FREE AGENT' : 'ROSTER');
    const topTagText = `${leaderCrown}${rankPart}${spotlight.position} · ${this.escapeHtml(mgrName.toUpperCase())}`;

    this.dom.highlightContainer.innerHTML = `
      <div class="spotlight-pill mvp-pill ${isFA ? 'is-free-agent' : ''}" style="border-color: ${this.hexToRgba(accentColor, 0.35)}; --hl-glow-color: ${this.hexToRgba(accentColor, 0.25)}; animation: pill-fade 0.35s cubic-bezier(0.16, 1, 0.3, 1);">
        <div class="spotlight-avatar-wrap">
          <img class="spotlight-avatar" src="${spotlight.headshot_url}" alt="${spotlight.player_name}" style="border-color: ${accentColor}; --team-color: ${accentColor};" onerror="window.hud && window.hud.handleAvatarError(this, '${spotlight.nfl_team || ""}', ${spotlight.position === "DEF"})" />
          <span class="spotlight-pos-badge" style="border-color: ${accentColor}; color: #ffffff; font-weight: 700; background: rgba(0, 0, 0, 0.85);">${spotlight.position}</span>
        </div>

        <div class="spotlight-info">
          <span class="spotlight-top-tag" style="color: ${accentColor}; font-weight: 700;">
            ${topTagText}
          </span>
          <span class="spotlight-player-name">${this.escapeHtml(this.formatPlayerDisplayName(spotlight.player_name, spotlight.position, spotlight.nfl_team))}</span>
        </div>

        <div class="spotlight-queue-slot"></div>

        <div class="spotlight-score-badge">
          <span class="spotlight-pts-value" style="color: #ffffff; font-weight: 600;">
            ${this.getBenchPrefix(spotlight)}<span class="pts-number">${pts.toFixed(1)}</span><span class="pts-sub" style="font-size: 9px; color: #ffffff; opacity: 0.85;">FPTS</span>
          </span>
        </div>
      </div>
    `;
  }


  // =========================================================================
  // Live Injury Alert System
  // =========================================================================
  enqueueInjury(injury) {
    if (!this.injuriesEnabled || !injury) return;
    this.injuryQueue.push(injury);

    if (!this.currentHighlight && !this.currentInjury) {
      this.stopIdleSpotlightCycle();
      this.playNextInjury();
    }
  }

  playNextInjury() {
    if (!this.injuriesEnabled) {
      this.injuryQueue = [];
      this.currentInjury = null;
      if (this.highlightQueue.length > 0) {
        this.playNextHighlight();
      } else if (!this.currentHighlight) {
        this.startIdleSpotlightCycle(true);
      }
      return;
    }
    if (this.injuryQueue.length === 0) {
      this.currentInjury = null;
      if (this.highlightQueue.length > 0) {
        this.playNextHighlight();
      } else if (!this.currentHighlight) {
        this.startIdleSpotlightCycle(true);
      }
      return;
    }

    const inj = this.injuryQueue.shift();
    this.currentInjury = inj;

    this.playInjurySound();

    const durationSec = this.getSpeedDurationSeconds();
    this.renderInjuryPill(inj, durationSec);

    const durationMs = durationSec * 1000;
    if (this.injuryTimer) clearTimeout(this.injuryTimer);

    this.injuryTimer = setTimeout(() => {
      this.playNextInjury();
    }, durationMs);
  }

  renderInjuryPill(inj, durationSec = 8) {
    if (!this.dom.highlightContainer || !inj) return;

    const rawStatus = (inj.injury_status || 'OUT').toUpperCase();
    const isOutOrIR = ['OUT', 'IR', 'INJURED RESERVE'].includes(rawStatus);
    const statusClass = isOutOrIR ? 'status-out' : 'status-ques';

    // Abbreviate QUESTIONABLE to QUES
    let displayStatus = rawStatus;
    if (displayStatus === 'QUESTIONABLE') {
      displayStatus = 'QUES';
    } else if (displayStatus === 'INJURED RESERVE') {
      displayStatus = 'IR';
    } else if (displayStatus === 'DOUBTFUL') {
      displayStatus = 'DOUBT';
    }

    // Border and progressbar always match the fantasy owner color
    const ownerColor = this.getOwnerColor(inj);

    const pts = Number(inj.points || 0);
    const benchPrefix = this.getBenchPrefix(inj);
    const shortName = this.formatPlayerDisplayName(inj.player_name, inj.position, inj.nfl_team);
    const mgrName = inj.manager_name || inj.fantasy_team_name || 'ROSTER';
    const topTagText = `🚑 ${displayStatus} · ${this.escapeHtml(mgrName.toUpperCase())}`;

    this.dom.highlightContainer.innerHTML = `
      <div class="spotlight-pill live-injury" style="border-color: ${ownerColor} !important; --hl-glow-color: ${ownerColor};">
        <div class="spotlight-avatar-wrap">
          <img class="spotlight-avatar" src="${inj.headshot_url || 'https://sleepercdn.com/images/v2/icons/player_default.webp'}" alt="${inj.player_name}" style="border-color: ${ownerColor}; --team-color: ${ownerColor};" onerror="window.hud && window.hud.handleAvatarError(this, '${inj.nfl_team || ""}', ${inj.position === "DEF"})" />
          <span class="spotlight-pos-badge" style="background: rgba(0, 0, 0, 0.85); border: 1.5px solid ${ownerColor}; color: #ffffff; font-weight: 800;">${inj.position || 'NFL'}</span>
        </div>

        <div class="spotlight-info">
          <span class="spotlight-top-tag" style="color: ${isOutOrIR ? '#fca5a5' : '#fef3c7'} !important;">
            ${topTagText}
          </span>
          <span class="spotlight-player-name">${this.escapeHtml(shortName)}</span>
        </div>

        <div class="spotlight-queue-slot" style="min-width: 50px;">
          <span class="injury-status-badge ${statusClass}">${this.escapeHtml(displayStatus)}</span>
        </div>

        <div class="spotlight-score-badge">
          <span class="spotlight-pts-value" style="color: #ffffff; font-weight: 600;">
            ${benchPrefix}<span class="pts-number">${pts.toFixed(1)}</span><span class="pts-sub" style="font-size: 9px; color: #ffffff; opacity: 0.85;">FPTS</span>
          </span>
        </div>

        <div class="spotlight-timer-bar" style="background: ${ownerColor} !important; animation: timer-shrink ${durationSec}s linear forwards;"></div>
      </div>
    `;
  }

  getInjurySoundUrl() {
    const themes = {
      whistle_blow: '/static/sounds/injury_whistle.wav',
      buzzer_flat: '/static/sounds/injury_buzzer.wav',
      flatline: '/static/sounds/injury_flatline.wav',
      record_scratch: '/static/sounds/injury_record_scratch.wav'
    };
    return themes[this.injurySoundTheme] || themes.whistle_blow;
  }

  playInjurySound() {
    if (!this.injurySoundEnabled) return;
    try {
      const audio = new Audio(this.getInjurySoundUrl());
      audio.volume = 0.85;
      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise.catch(() => {});
      }
    } catch (e) {}
  }

  // =========================================================================
  // Audio & Sound FX System
  // =========================================================================
  initSoundControls() {
    this.updateSoundUI();

    if (this.dom.soundToggleBtn) {
      this.dom.soundToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleSound();
      });
    }
  }

  updateSoundUI() {
    const btn = this.dom.soundToggleBtn;
    const icon = this.dom.soundIcon;
    if (!btn) return;

    if (this.soundEnabled) {
      btn.classList.remove('is-muted');
      if (icon) icon.textContent = '🔊';
      btn.title = "Highlight Sound: ON (Press 'M' to mute)";
      btn.setAttribute('aria-label', 'Mute highlight sound');
    } else {
      btn.classList.add('is-muted');
      if (icon) icon.textContent = '🔇';
      btn.title = "Highlight Sound: MUTED (Press 'M' to unmute)";
      btn.setAttribute('aria-label', 'Unmute highlight sound');
    }
  }

  toggleSound(forcedState = null) {
    if (forcedState !== null) {
      this.soundEnabled = Boolean(forcedState);
    } else {
      this.soundEnabled = !this.soundEnabled;
    }

    localStorage.setItem('nfl_hud_sound_enabled', this.soundEnabled ? 'true' : 'false');
    this.updateSoundUI();

    const toastMsg = this.soundEnabled ? '🔊 Sound FX Enabled' : '🔇 Sound FX Muted';
    this.showToast(toastMsg);

    if (this.soundEnabled) {
      this.playPreviewChirp();
    }

    fetch('/api/settings/sound', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sound_enabled: this.soundEnabled })
    }).catch(() => {});
  }

  setSound(enabled) {
    this.toggleSound(enabled);
  }

  showToast(message, durationMs = 2000) {
    const toast = this.dom.toast;
    if (!toast) return;

    toast.textContent = message;
    toast.classList.add('show');

    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, durationMs);
  }

  playPreviewChirp() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!this.audioCtx) this.audioCtx = new AudioCtx();
      if (this.audioCtx.state === 'suspended') this.audioCtx.resume();
      
      const ctx = this.audioCtx;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const now = ctx.currentTime;
      
      osc.type = 'sine';
      osc.frequency.setValueAtTime(523.25, now);
      osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.12);
      
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
      
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.2);
    } catch (e) {}
  }

  getSoundUrl() {
    const themes = {
      fox_horn: '/static/sounds/nfl_fox_horn.wav',
      redzone: '/static/sounds/nfl_redzone_alert.wav',
      td_siren: '/static/sounds/nfl_touchdown_siren.wav',
      brass_fanfare: '/static/sounds/nfl_brass_fanfare.wav'
    };
    return themes[this.soundTheme] || themes.fox_horn;
  }

  playNFLFanfareSound() {
    if (!this.soundEnabled) return;

    try {
      const audio = new Audio(this.getSoundUrl());
      audio.volume = 0.85;
      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise.catch(() => {
          this.synthesizeFanfare();
        });
        return;
      }
    } catch (e) {
      this.synthesizeFanfare();
    }
  }

  synthesizeFanfare() {
    if (!this.soundEnabled) return;

    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!this.audioCtx) {
        this.audioCtx = new AudioCtx();
      }
      if (this.audioCtx.state === 'suspended') {
        this.audioCtx.resume();
      }

      const ctx = this.audioCtx;
      const now = ctx.currentTime;

      const masterGain = ctx.createGain();
      masterGain.gain.setValueAtTime(0.4, now);
      masterGain.connect(ctx.destination);

      const kickOsc = ctx.createOscillator();
      const kickGain = ctx.createGain();
      kickOsc.type = 'sine';
      kickOsc.frequency.setValueAtTime(90, now);
      kickOsc.frequency.exponentialRampToValueAtTime(25, now + 0.25);
      kickGain.gain.setValueAtTime(0.5, now);
      kickGain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
      kickOsc.connect(kickGain);
      kickGain.connect(masterGain);
      kickOsc.start(now);
      kickOsc.stop(now + 0.28);

      const notes = [
        { start: 0.00, end: 0.12, freqs: [392.00], vol: 0.75 },
        { start: 0.12, end: 0.24, freqs: [523.25], vol: 0.80 },
        { start: 0.24, end: 0.36, freqs: [659.25], vol: 0.85 },
        { start: 0.36, end: 1.30, freqs: [523.25, 659.25, 783.99, 1046.50], vol: 0.95 }
      ];

      notes.forEach((n) => {
        const t0 = now + n.start;
        const dur = n.end - n.start;
        const isChord = n.freqs.length > 1;

        n.freqs.forEach((f) => {
          [-1.5, 1.5].forEach((detune) => {
            const osc = ctx.createOscillator();
            const filter = ctx.createBiquadFilter();
            const noteGain = ctx.createGain();

            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(f, t0);
            osc.detune.setValueAtTime(detune * 4, t0);

            filter.type = 'lowpass';
            filter.frequency.setValueAtTime(1450, t0);

            const v = (isChord ? 0.08 : 0.18) * n.vol;
            noteGain.gain.setValueAtTime(0.0001, t0);
            noteGain.gain.linearRampToValueAtTime(v, t0 + 0.015);
            if (isChord) {
              noteGain.gain.setValueAtTime(v, t0 + 0.3);
              noteGain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
            } else {
              noteGain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
            }

            osc.connect(filter);
            filter.connect(noteGain);
            noteGain.connect(masterGain);

            osc.start(t0);
            osc.stop(t0 + dur);
          });
        });
      });

      const cTime = now + 0.36;
      [2093, 3136].forEach((freq) => {
        const chimeOsc = ctx.createOscillator();
        const chimeGain = ctx.createGain();
        chimeOsc.type = 'sine';
        chimeOsc.frequency.setValueAtTime(freq, cTime);
        chimeGain.gain.setValueAtTime(0.07, cTime);
        chimeGain.gain.exponentialRampToValueAtTime(0.0001, cTime + 0.55);
        chimeOsc.connect(chimeGain);
        chimeGain.connect(masterGain);
        chimeOsc.start(cTime);
        chimeOsc.stop(cTime + 0.6);
      });
    } catch (e) {
      console.warn('Synthesis error:', e);
    }
  }

  // Keyboard controls
  initKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      if (['input', 'textarea', 'select'].includes((e.target.tagName || '').toLowerCase())) {
        return;
      }

      const key = e.key.toLowerCase();
      if (key === 'm') {
        this.toggleSound();
      } else if (key === 't') {
        this.cycleTheme();
      } else if (key === 'h') {
        const topBar = this.dom.topBar;
        if (topBar) {
          const isHidden = topBar.style.transform === 'translateY(-100%)';
          topBar.style.transform = isHidden ? 'translateY(0%)' : 'translateY(-100%)';
          this.showToast(isHidden ? '👁️ HUD Visible' : '🙈 HUD Hidden (Press H to restore)');
        }
      }
    });
  }

  handleAvatarError(img, nflTeam, isDefense) {
    if (!img) return;
    if (img.dataset.failedOnce) {
      img.src = "https://sleepercdn.com/images/v2/icons/player_default.webp";
      return;
    }
    img.dataset.failedOnce = "true";
    if (isDefense && nflTeam) {
      img.src = `https://a.espncdn.com/i/teamlogos/nfl/500/${nflTeam.toLowerCase()}.png`;
    } else {
      img.src = "https://sleepercdn.com/images/v2/icons/player_default.webp";
    }
  }

  // Utilities
  hexToRgba(hex, alpha = 1) {
    if (!hex || !hex.startsWith('#')) return `rgba(255,255,255,${alpha})`;
    let c = hex.substring(1);
    if (c.length === 3) {
      c = c.split('').map(x => x + x).join('');
    }
    const num = parseInt(c, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

// Instantiate on load
document.addEventListener('DOMContentLoaded', () => {
  window.hud = new NFLGameHUD();
});
