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
    this.soundEnabled = localStorage.getItem('nfl_hud_sound_enabled') !== 'false';
    this.soundTheme = localStorage.getItem('nfl_hud_sound_theme') || 'fox_horn';
    this.audioCtx = null;
    this.toastTimer = null;
    
    this.dom = {
      topBar: document.getElementById('hud-top-bar'),
      weekTag: document.getElementById('hud-week-tag'),
      soundToggleBtn: document.getElementById('hud-sound-toggle'),
      soundIcon: document.getElementById('sound-icon'),
      toast: document.getElementById('hud-toast'),
      matchupsContainer: document.getElementById('matchups-container'),
      highlightContainer: document.getElementById('highlight-container')
    };

    this.initSoundControls();
    this.initWebSocket();
    this.initKeyboardShortcuts();
  }

  // =========================================================================
  // WebSocket Connection & Handling
  // =========================================================================
  initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:8080';
    const wsUrl = `${protocol}//${host}/ws`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.heartbeatInterval = setInterval(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'PING' }));
          }
        }, 15000);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (e) {
          console.error('[HUD] Failed to parse WS message:', e);
        }
      };

      this.ws.onclose = () => {
        clearInterval(this.heartbeatInterval);
        this.attemptReconnect();
      };

      this.ws.onerror = (err) => {
        console.warn('[HUD] WebSocket error:', err);
      };
    } catch (e) {
      console.error('[HUD] WebSocket init failed:', e);
      this.attemptReconnect();
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(10000, this.reconnectDelay * Math.pow(1.2, this.reconnectAttempts));
      setTimeout(() => this.initWebSocket(), delay);
    }
  }

  handleMessage(msg) {
    switch (msg.type) {
      case 'INITIAL_STATE':
      case 'UPDATE_MATCHUPS':
        this.renderState(msg.state);
        break;
      case 'UPDATE_DISPLAY_SETTINGS':
        if (msg.settings) {
          this.applyDisplaySettings(msg.settings);
        }
        break;
      case 'PUSH_HIGHLIGHT':
        this.enqueueHighlight(msg.highlight);
        break;
      case 'PONG':
        break;
      default:
        break;
    }
  }

  applyDisplaySettings(settings) {
    let speedChanged = false;
    let modeChanged = false;

    if (settings.mode) {
      const newMode = (settings.mode === 'paged') ? 'step' : settings.mode;
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
    
    // Sync sound if server explicitly passed it and client hasn't pinned it
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
    
    if (speedChanged) {
      this.restartIdleTimer();
      // If step shift mode is active, restart interval with new timing
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
  renderState(state) {
    if (!state) return;
    this.state = state;

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

    // 2. Update Position MVPs list
    const incomingMVPs = state.idle_spotlights || (state.idle_spotlight ? [state.idle_spotlight] : []);
    this.idleSpotlights = incomingMVPs;

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
      const scoreA = teamA ? teamA.points : 0;
      const scoreB = teamB ? teamB.points : 0;
      const totalScore = scoreA + scoreB;
      const pctA = totalScore > 0 ? ((scoreA / totalScore) * 100).toFixed(1) : 50;
      const pctB = (100 - pctA).toFixed(1);

      const scoreElA = card.querySelector('.score-a');
      const scoreElB = card.querySelector('.score-b');
      const leaderRosterId = m.leader_roster_id;

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
        if (leaderRosterId === (teamA && teamA.roster_id)) {
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
        if (leaderRosterId === (teamB && teamB.roster_id)) {
          scoreElB.classList.add('leading');
        } else {
          scoreElB.classList.remove('leading');
        }
      }

      const barA = card.querySelector('.score-bar-left');
      const barB = card.querySelector('.score-bar-right');
      if (barA) barA.style.width = `${pctA}%`;
      if (barB) barB.style.width = `${pctB}%`;
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

      const firstCard = track.querySelector('.matchup-card');
      if (!firstCard) {
        isShifting = false;
        return;
      }

      const gap = 12;
      const shiftDistance = firstCard.offsetWidth + gap;

      track.classList.add('sliding');
      track.style.transform = `translate3d(-${shiftDistance}px, 0, 0)`;

      setTimeout(() => {
        this.stepIndex = (this.stepIndex + 1) % count;
        populateTrack(this.stepIndex);
        isShifting = false;
      }, 660);

    }, this.stepInterval);
  }

  // 3. Glitch-Free Continuous Ticker (Seamless Infinite Marquee)
  renderContinuousTicker(matchups) {
    const container = this.dom.matchupsContainer;
    container.className = 'matchups-container ticker-mode';
    container.innerHTML = '';

    if (matchups.length === 0) return;

    const track = document.createElement('div');
    track.className = 'ticker-track';

    const doubleList = [...matchups, ...matchups];
    doubleList.forEach((m) => {
      const card = this.createMatchupCardElement(m);
      card.classList.add('ticker-card');
      track.appendChild(card);
    });

    container.appendChild(track);

    this.tickerOffset = 0;
    this.lastTimestamp = null;

    const animate = (timestamp) => {
      if (!this.lastTimestamp) this.lastTimestamp = timestamp;
      const delta = (timestamp - this.lastTimestamp) / 1000.0;
      this.lastTimestamp = timestamp;

      const singleSetWidth = track.scrollWidth / 2;

      if (!this.isPaused && singleSetWidth > 0) {
        this.tickerOffset += this.tickerSpeed * delta;
        if (this.tickerOffset >= singleSetWidth) {
          this.tickerOffset = this.tickerOffset % singleSetWidth;
        }
        track.style.transform = `translate3d(-${this.tickerOffset.toFixed(2)}px, 0, 0)`;
      }

      this.tickerAnimationId = requestAnimationFrame(animate);
    };

    this.tickerAnimationId = requestAnimationFrame(animate);
  }

  // Helper to create single matchup card DOM with glowing manager colors
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
    const pctA = totalScore > 0 ? ((scoreA / totalScore) * 100).toFixed(1) : 50;
    const pctB = (100 - pctA).toFixed(1);

    const flashA = this.checkScoreFlash(teamA ? teamA.roster_id : null, scoreA);
    const flashB = this.checkScoreFlash(teamB ? teamB.roster_id : null, scoreB);

    const leaderRosterId = m.leader_roster_id;

    card.innerHTML = `
      <div class="matchup-teams-row">
        <img class="team-avatar" src="${teamA ? teamA.avatar_url : ''}" alt="${teamA ? teamA.manager_name : ''}" title="${teamA ? teamA.manager_name : ''}" style="border-color: ${colorA}; box-shadow: 0 0 8px ${this.hexToRgba(colorA, 0.45)};" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'" />

        <div class="matchup-center-scores">
          <span class="team-score score-a ${leaderRosterId === (teamA && teamA.roster_id) ? 'leading' : ''} ${flashA ? 'score-flash' : ''}">
            ${scoreA.toFixed(1)}
          </span>
          <span class="vs-divider">-</span>
          <span class="team-score score-b ${leaderRosterId === (teamB && teamB.roster_id) ? 'leading' : ''} ${flashB ? 'score-flash' : ''}">
            ${scoreB.toFixed(1)}
          </span>
        </div>

        <img class="team-avatar" src="${teamB ? teamB.avatar_url : ''}" alt="${teamB ? teamB.manager_name : ''}" title="${teamB ? teamB.manager_name : ''}" style="border-color: ${colorB}; box-shadow: 0 0 8px ${this.hexToRgba(colorB, 0.45)};" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'" />
      </div>

      <div class="score-progress-bar">
        <div class="score-bar-left" style="width: ${pctA}%; background: ${colorA}; box-shadow: 0 0 8px ${this.hexToRgba(colorA, 0.75)};"></div>
        <div class="score-bar-right" style="width: ${pctB}%; background: ${colorB}; box-shadow: 0 0 8px ${this.hexToRgba(colorB, 0.75)};"></div>
      </div>
    `;

    return card;
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
    if (this.currentHighlight) return;

    if (!this.idleSpotlights || this.idleSpotlights.length === 0) {
      this.stopIdleSpotlightCycle();
      if (this.dom.highlightContainer) {
        this.dom.highlightContainer.innerHTML = `
          <div class="spotlight-pill mvp-pill pregame-pill" style="border-color: rgba(255, 255, 255, 0.15); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);">
            <div class="spotlight-avatar-wrap" style="display: flex; align-items: center; justify-content: center; font-size: 16px; background: rgba(255,255,255,0.06); border-radius: 50%;">
              🏈
            </div>
            <div class="spotlight-info">
              <span class="spotlight-top-tag" style="color: var(--color-text-dim); font-weight: 800;">PREGAME</span>
              <span class="spotlight-player-name" style="color: #cbd5e1; font-size: 13px;">Awaiting Kickoff</span>
            </div>
            <div class="spotlight-score-badge">
              <span class="spotlight-pts-value" style="color: var(--color-text-dim); font-weight: 700;">
                0.0 <span style="font-size: 9px; color: var(--color-text-dim);">PTS</span>
              </span>
            </div>
          </div>
        `;
      }
      return;
    }

    const hasMvpCard = this.dom.highlightContainer && !!this.dom.highlightContainer.querySelector('.mvp-pill');

    // Immediately swap to MVP card if a highlight just finished or no MVP is showing
    if (!hasMvpCard || forceImmediate) {
      this.stopIdleSpotlightCycle();
      if (this.currentSpotlightIndex >= this.idleSpotlights.length) {
        this.currentSpotlightIndex = 0;
      }
      this.renderIdleSpotlight(this.idleSpotlights[this.currentSpotlightIndex]);
    }

    if (this.idleTimer) return;

    this.idleTimer = setInterval(() => {
      if (!this.currentHighlight && this.idleSpotlights && this.idleSpotlights.length > 0) {
        this.currentSpotlightIndex = (this.currentSpotlightIndex + 1) % this.idleSpotlights.length;
        this.renderIdleSpotlight(this.idleSpotlights[this.currentSpotlightIndex]);
      }
    }, this.idleIntervalMs);
  }

  restartIdleTimer() {
    this.stopIdleSpotlightCycle();
    if (!this.currentHighlight) {
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
    if (!highlight) return;
    this.highlightQueue.push(highlight);
    
    if (!this.currentHighlight) {
      this.stopIdleSpotlightCycle();
      this.playNextHighlight();
    } else {
      this.updateQueueBadge();
      
      // Jiggle the currently displayed highlight box to signal a new big play in queue!
      const activeCard = this.dom.highlightContainer.querySelector('.spotlight-pill.live-highlight');
      if (activeCard) {
        activeCard.classList.remove('jiggling');
        void activeCard.offsetWidth; // Force CSS reflow to retrigger animation
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
    if (this.highlightQueue.length === 0) {
      this.currentHighlight = null;
      this.startIdleSpotlightCycle(true); // Seamlessly return to MVP cards the instant timer finishes
      return;
    }

    const hl = this.highlightQueue.shift();
    this.currentHighlight = hl;
    
    // Play authentic NFL broadcast fanfare sound FX!
    this.playNFLFanfareSound();

    const durationSec = this.getSpeedDurationSeconds();
    this.renderHighlightPill(hl, durationSec);

    const durationMs = durationSec * 1000;
    if (this.highlightTimer) clearTimeout(this.highlightTimer);
    
    this.highlightTimer = setTimeout(() => {
      this.playNextHighlight();
    }, durationMs);
  }

  formatHighlightDisplayName(name, position, nflTeam) {
    if (!name) return '';
    const pos = (position || '').toUpperCase();
    
    // For defenses, display only the 3-letter (or 2-3 char) NFL team code
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
        'ARIZONA CARDINALS': 'ARI', 'TENNESSEE TITANS': 'TEN', 'WASHINGTON COMMANDERS': 'WAS'
      };
      for (const [key, abbr] of Object.entries(teamMap)) {
        if (upperName.includes(key) || key.includes(upperName)) {
          return abbr;
        }
      }
      return upperName.replace(/DEFENSE|DEF/i, '').trim().substring(0, 3).toUpperCase();
    }

    // For players: Jersey name format (First initial. Surname [suffix])
    const parts = name.trim().split(/\s+/);
    if (parts.length <= 1) return name;

    const firstName = parts[0];
    const initial = firstName.charAt(0).toUpperCase() + '.';
    const surname = parts.slice(1).join(' ');

    return `${initial} ${surname}`;
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

  renderHighlightPill(hl, durationSec = 10) {
    if (!this.dom.highlightContainer) return;

    const accentColor = hl.color_accent || '#94a3b8';
    const tagText = hl.is_free_agent ? 'FREE AGENT' : (hl.fantasy_team_name || 'LIVE PLAY');
    const remaining = this.highlightQueue.length;
    const showQueue = remaining > 0 ? '' : 'display: none;';

    const header = this.getHighlightHeaderInfo(hl);

    this.dom.highlightContainer.innerHTML = `
      <div class="spotlight-pill live-highlight" style="border-color: ${accentColor}; --hl-glow-color: ${accentColor};">
        <div class="spotlight-avatar-wrap">
          <img class="spotlight-avatar" src="${hl.headshot_url}" alt="${hl.player_name}" style="border-color: ${accentColor}; box-shadow: 0 0 10px ${this.hexToRgba(accentColor, 0.6)};" onerror="window.hud && window.hud.handleAvatarError(this, '${hl.nfl_team || ""}', ${hl.position === "DEF"})" />
          <span class="spotlight-pos-badge" style="background: ${accentColor}; color: #000; font-weight: 900;">${hl.position}</span>
        </div>

        <div class="spotlight-info">
          <span class="spotlight-top-tag" style="color: ${accentColor}; font-weight: 800; text-shadow: 0 0 8px ${this.hexToRgba(accentColor, 0.5)};">
            ${header.emoji} ${header.label}
          </span>
          <span class="spotlight-player-name">${this.escapeHtml(this.formatHighlightDisplayName(hl.player_name, hl.position, hl.nfl_team))}</span>
        </div>

        <div class="spotlight-queue-slot">
          <span class="spotlight-queue-badge" id="spotlight-queue-badge" style="${showQueue}">+${remaining} IN QUEUE</span>
        </div>

        <div class="spotlight-score-badge">
          <span class="spotlight-pts-value" style="color: ${accentColor}; border: 1.5px solid ${accentColor} !important; background: ${this.hexToRgba(accentColor, 0.18)} !important; box-shadow: 0 0 12px ${this.hexToRgba(accentColor, 0.45)} !important; font-weight: 900; text-shadow: 0 0 10px ${this.hexToRgba(accentColor, 0.65)};">
            +${hl.delta_points.toFixed(1)}<span class="pts-sub" style="color: ${this.hexToRgba(accentColor, 0.85)};">FPTS</span>
          </span>
        </div>

        <div class="spotlight-timer-bar" style="background: ${accentColor}; box-shadow: 0 0 8px ${this.hexToRgba(accentColor, 0.75)}; animation: timer-shrink ${durationSec}s linear forwards;"></div>
      </div>
    `;
  }

  renderIdleSpotlight(spotlight) {
    if (!this.dom.highlightContainer || !spotlight) return;

    const isFA = spotlight.is_free_agent;
    const isStarter = spotlight.is_starter !== false && spotlight.roster_slot !== 'BENCH';
    const accentColor = spotlight.color_accent || (isFA ? '#94a3b8' : '#00f0ff');
    
    // Choose rank / icon emoji
    const rankEmoji = spotlight.rank === 1 ? '👑' : (isStarter ? '⭐' : '⚡');
    
    // Roster slot badge
    const slotBadge = isStarter
      ? `<span class="spotlight-slot-badge starter-badge">START</span>`
      : `<span class="spotlight-slot-badge bench-badge">BENCH</span>`;

    // Position & Rank text
    const posRankText = spotlight.rank 
      ? `${spotlight.position} #${spotlight.rank}` 
      : `${spotlight.position}`;

    const mgrName = spotlight.manager_name || spotlight.fantasy_team_name || 'ROSTER';

    this.dom.highlightContainer.innerHTML = `
      <div class="spotlight-pill mvp-pill ${isFA ? 'is-free-agent' : ''} ${!isStarter ? 'is-bench' : ''}" style="border-color: ${this.hexToRgba(accentColor, 0.45)}; --hl-glow-color: ${this.hexToRgba(accentColor, 0.25)}; box-shadow: 0 0 10px ${this.hexToRgba(accentColor, 0.25)}, 0 4px 16px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05); animation: pill-fade 0.35s cubic-bezier(0.16, 1, 0.3, 1);">
        <div class="spotlight-avatar-wrap">
          <img class="spotlight-avatar" src="${spotlight.headshot_url}" alt="${spotlight.player_name}" style="border-color: ${accentColor}; box-shadow: 0 0 8px ${this.hexToRgba(accentColor, 0.35)};" onerror="window.hud && window.hud.handleAvatarError(this, '${spotlight.nfl_team || ""}', ${spotlight.position === "DEF"})" />
          <span class="spotlight-pos-badge" style="border-color: ${accentColor}; color: ${accentColor}; font-weight: 800;">${spotlight.position}</span>
        </div>

        <div class="spotlight-info">
          <span class="spotlight-top-tag" style="color: ${accentColor}; font-weight: 800; text-shadow: 0 0 6px ${this.hexToRgba(accentColor, 0.3)};">
            ${isFA ? '🆓' : rankEmoji} ${posRankText} · ${this.escapeHtml(mgrName.toUpperCase())} ${slotBadge}
          </span>
          <span class="spotlight-player-name">${this.escapeHtml(spotlight.player_name)}</span>
        </div>

        <div class="spotlight-queue-slot"></div>

        <div class="spotlight-score-badge">
          <span class="spotlight-pts-value" style="color: #ffffff; font-weight: 800;">
            ${spotlight.points.toFixed(1)} <span style="font-size: 9px; color: var(--color-text-dim); margin-left: 2px;">PTS</span>
          </span>
        </div>
      </div>
    `;
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

    // If unmuting, play a subtle chime preview
    if (this.soundEnabled) {
      this.playPreviewChirp();
    }

    // Sync with backend API
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

    // 1. Try playing pre-generated broadcast WAV
    try {
      const audio = new Audio(this.getSoundUrl());
      audio.volume = 0.85;
      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise.catch(() => {
          // Fallback to Web Audio API synthesizer
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

      // Sub-bass stadium kick impact
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

      // Fanfare Brass Sequence: G4 -> C5 -> E5 -> Chord (C5, E5, G5, C6)
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

      // Chime sparkle at t=0.36
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
