// ================================================
// Export Advisory System — Frontend JavaScript
// ================================================

// === CONFIG ===
const API_BASE = window.location.origin;
let currentSessionId = localStorage.getItem('export_session_id') || 'default';
let chartCounter = 0;
const chartInstances = {};

// === DOM ELEMENTS ===
const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const newSessionBtn = document.getElementById('new-session-btn');
const clearSessionBtn = document.getElementById('clear-session-btn');
const sessionDisplay = document.getElementById('session-display');

// === INITIALIZATION ===
document.addEventListener('DOMContentLoaded', () => {
    console.log('Export Advisory System initialized');

    // Restore session ID display
    if (currentSessionId !== 'default') {
        sessionDisplay.textContent = `Session: ${currentSessionId.substring(0, 20)}...`;
    }

    // Setup event listeners
    sendBtn.addEventListener('click', handleSendMessage);
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    });

    newSessionBtn.addEventListener('click', handleNewSession);
    clearSessionBtn.addEventListener('click', handleClearSession);

    // Setup example query clicks
    document.querySelectorAll('.example-queries li').forEach(li => {
        li.addEventListener('click', () => {
            const query = li.getAttribute('data-query') || li.textContent.replace(/^[^\s]+\s/, '').replace(/^"|"$/g, '');
            userInput.value = query;
            handleSendMessage();
        });
    });

    // Auto-resize textarea
    userInput.addEventListener('input', () => {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 150) + 'px';
    });

    // Configure marked.js
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            sanitize: false
        });
    }

    // Check server health then restore session history
    checkHealth().then(() => {
        restoreSessionHistory();
    });
});

// === SESSION HISTORY RESTORATION ===

async function restoreSessionHistory() {
    try {
        const response = await fetch(`${API_BASE}/api/session/${currentSessionId}/history`);
        if (!response.ok) return;

        const data = await response.json();
        if (!data.history || data.history.length === 0) return;

        // Hide welcome message since we have history
        const welcome = document.getElementById('welcome-message');
        if (welcome) welcome.style.display = 'none';

        // Render previous messages
        for (const msg of data.history) {
            if (msg.role === 'user') {
                addUserMessage(msg.content);
            } else if (msg.role === 'assistant') {
                // Render as a simple restored message (no metadata available)
                addRestoredAssistantMessage(msg.content);
            }
        }

        addSystemMessage(`Restored ${data.message_count} messages from previous session`);
        scrollToBottom();
    } catch (error) {
        console.log('No previous session to restore:', error.message);
    }
}

function addRestoredAssistantMessage(content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-assistant';

    const formattedAnswer = formatMessageContent(content);

    messageDiv.innerHTML = `
        <div class="assistant-avatar">EA</div>
        <div class="message-body">
            <div class="message-header">Assistant</div>
            <div class="message-content">
                ${formattedAnswer}
                <div class="message-meta">
                    <span class="meta-tag">Session Restore</span>
                </div>
            </div>
        </div>
    `;

    chatMessages.appendChild(messageDiv);
}

// === API CALLS ===

async function checkHealth() {
    try {
        const response = await fetch(`${API_BASE}/api/health`);
        const data = await response.json();
        console.log('Server health:', data);
        if (data.status !== 'healthy') {
            addSystemMessage('Server is not fully initialized. Some features may be unavailable.');
        }
    } catch (error) {
        console.error('Health check failed:', error);
        addSystemMessage('Cannot connect to server. Please check if the backend is running.');
    }
}

async function sendQuery(query) {
    const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query: query,
            session_id: currentSessionId
        })
    });

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `API error: ${response.status}`);
    }

    return await response.json();
}

async function clearSession(sessionId) {
    const response = await fetch(`${API_BASE}/api/session/${sessionId}`, {
        method: 'DELETE'
    });

    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return await response.json();
}

async function getTradeData(hsCode = null, chapter = null) {
    const response = await fetch(`${API_BASE}/api/trade-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            hs_code: hsCode,
            chapter: chapter,
            countries: ['australia', 'uae', 'uk']
        })
    });

    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return await response.json();
}

async function getMonthlyTradeData(hsCode = null, chapter = null) {
    const response = await fetch(`${API_BASE}/api/monthly-trade-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            hs_code: hsCode,
            chapter: chapter,
            countries: ['australia', 'uae', 'uk']
        })
    });

    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return await response.json();
}

// === MESSAGE HANDLING ===

async function handleSendMessage() {
    const query = userInput.value.trim();
    if (!query) return;

    // Clear input
    userInput.value = '';
    userInput.style.height = 'auto';
    setLoading(true);

    // Hide welcome message
    const welcome = document.getElementById('welcome-message');
    if (welcome) welcome.style.display = 'none';

    // Add user message
    addUserMessage(query);

    try {
        const response = await sendQuery(query);

        // Add assistant response and get the message element back
        const msgDiv = addAssistantMessage(response);

        // Embed chart directly inside the message bubble
        await embedChartInMessage(msgDiv, response, query);

    } catch (error) {
        console.error('Error sending message:', error);
        addSystemMessage(`Error: ${error.message}`);
    } finally {
        setLoading(false);
    }
}

function addUserMessage(content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-user';
    messageDiv.innerHTML = `
        <div class="message-header">You</div>
        <div class="message-content">${escapeHtml(content)}</div>
    `;
    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

function addAssistantMessage(response) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-assistant';

    // Format answer with markdown
    const formattedAnswer = formatMessageContent(response.answer);

    // Build sources HTML
    let sourcesHtml = '';
    if (response.sources && response.sources.length > 0) {
        sourcesHtml = `
            <div class="message-sources">
                <h4>Sources</h4>
                ${response.sources.map(source => `
                    <div class="source-item">
                        <strong>${(source.type || 'info').toUpperCase()}</strong>: ${formatSource(source)}
                    </div>
                `).join('')}
            </div>
        `;
    }

    // Build meta tags
    let metaHtml = '<div class="message-meta">';
    if (response.query_type) {
        metaHtml += `<span class="meta-tag">${getQueryTypeLabel(response.query_type)}</span>`;
    }
    if (response.hs_code) {
        metaHtml += `<span class="meta-tag">HS: ${response.hs_code}</span>`;
    }
    if (response.country) {
        metaHtml += `<span class="meta-tag">Country: ${response.country.toUpperCase()}</span>`;
    }
    metaHtml += `<span class="meta-tag">${new Date(response.timestamp).toLocaleTimeString()}</span>`;
    metaHtml += '</div>';

    messageDiv.innerHTML = `
        <div class="assistant-avatar">EA</div>
        <div class="message-body">
            <div class="message-header">Assistant</div>
            <div class="message-content">
                ${formattedAnswer}
                ${sourcesHtml}
                ${metaHtml}
            </div>
        </div>
    `;

    chatMessages.appendChild(messageDiv);
    scrollToBottom();

    return messageDiv;
}

function addSystemMessage(content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-system';
    messageDiv.innerHTML = `
        <div class="message-content">${escapeHtml(content)}</div>
    `;
    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

function getQueryTypeLabel(type) {
    const labels = {
        'sql': 'Data Query',
        'policy': 'Policy Check',
        'vector': 'Document Search',
        'general': 'General',
        'combined': 'Multi-Agent',
        'agreements': 'Agreements',
        'hs_lookup': 'HS Lookup'
    };
    return labels[type] || `Type: ${String(type).replace(/_/g, ' ')}`;
}

function formatMessageContent(content) {
    if (!content) return '';

    // Use marked.js for Markdown rendering if available
    if (typeof marked !== 'undefined') {
        try {
            return marked.parse(content);
        } catch (e) {
            console.warn('Markdown parsing error, falling back to basic formatting:', e);
        }
    }

    // Fallback: basic formatting
    let formatted = escapeHtml(content);
    formatted = formatted.replace(/\n/g, '<br>');
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/•/g, '<strong>•</strong>');
    return formatted;
}

function formatSource(source) {
    if (source.type === 'sql') {
        return `Query: <code>${escapeHtml(source.query || 'N/A')}</code>`;
    } else if (source.type === 'policy_check') {
        const country = source.country ? source.country.toUpperCase() : 'ALL';
        return `HS: ${source.hs_code || 'N/A'} → ${country}`;
    } else if (source.type === 'vector_search') {
        const stores = Array.isArray(source.stores) ? source.stores.filter(Boolean) : [];
        const storeLabel = source.store || (stores.length > 0 ? stores.join(', ') : 'vector');

        let resultCount = source.num_results;
        if (resultCount === undefined || resultCount === null) {
            const dgftCount = Number(source.dgft_ftp_results ?? 0);
            const agreementCount = Number(source.agreement_results ?? 0);
            if (Number.isFinite(dgftCount) && Number.isFinite(agreementCount)) {
                resultCount = dgftCount + agreementCount;
            }
        }

        const hasValidCount = resultCount !== undefined && resultCount !== null && !Number.isNaN(Number(resultCount));
        return `${escapeHtml(String(storeLabel))} (${hasValidCount ? resultCount : '?'} results)`;
    } else if (source.type === 'hs_master_lookup') {
        const ambig = source.is_ambiguous ? ' (AMBIGUOUS)' : '';
        return `${source.matches_found || 0} matches for "${source.search_term || '?'}"${ambig}`;
    } else if (source.type === 'trade_agreements') {
        const agreements = source.agreements?.join(', ') || 'N/A';
        const results = source.num_results ?? '?';
        return `${results} results from ${agreements}`;
    }
    return escapeHtml(JSON.stringify(source));
}

// === SESSION MANAGEMENT ===

function handleNewSession() {
    const sessionId = `session_${Date.now()}`;
    currentSessionId = sessionId;
    localStorage.setItem('export_session_id', sessionId);
    sessionDisplay.textContent = `Session: ${sessionId.substring(0, 20)}...`;

    // Reset chat
    chatMessages.innerHTML = '';

    addSystemMessage(`Started new session: ${sessionId}`);
}

async function handleClearSession() {
    if (!confirm('Clear conversation history for this session?')) return;

    try {
        await clearSession(currentSessionId);
        chatMessages.innerHTML = '';

        // Reset to default session
        currentSessionId = 'default';
        localStorage.setItem('export_session_id', 'default');
        sessionDisplay.textContent = 'Session: default';

        addSystemMessage('Session cleared successfully');
    } catch (error) {
        console.error('Error clearing session:', error);
        addSystemMessage(`Error clearing session: ${error.message}`);
    }
}

// === INLINE CHART EMBEDDING ===

async function embedChartInMessage(msgDiv, response, queryText = '') {
    try {
        // HS codes that actually have trade data in the database (6-digit)
        const KNOWN_TRADE_CODES = new Set([
            '070310','070700','070960',
            '080310','080410','080450',
            '610910','610342','610442',
            '620342','620462','620520',
            '850440','851310','851762',
            '902610',
        ]);
        const KNOWN_CHAPTERS = new Set(Array.from(KNOWN_TRADE_CODES).map(code => code.substring(0, 2)));

        // --- Collect HS code candidates (6-8 digit) ---
        // Priority:
        // 1) explicit HS codes in THIS user query
        // 2) response.hs_code from backend
        // 3) strict fallback from answer text (only "HS xxxx" patterns)
        // This prevents accidental charting from unrelated code lists in model output.
        const hsCandidates = [];
        const addHsCandidate = (rawCode) => {
            if (rawCode === undefined || rawCode === null) return;
            const code = String(rawCode).trim();
            if (!/^\d{6,8}$/.test(code)) return;
            if (code.startsWith('202') || code.startsWith('201') || code.startsWith('200')) return;
            if (!hsCandidates.includes(code)) hsCandidates.push(code);
        };

        if (queryText) {
            for (const m of queryText.matchAll(/\b(\d{6,8})\b/g)) {
                addHsCandidate(m[1]);
            }
        }

        const hasExplicitQueryHs = hsCandidates.length > 0;

        if (!hasExplicitQueryHs && response.hs_code) {
            addHsCandidate(response.hs_code);
        }

        if (!hasExplicitQueryHs && hsCandidates.length === 0 && response.answer) {
            for (const m of response.answer.matchAll(/\bHS\s*[:#-]?\s*(\d{6,8})\b/gi)) {
                addHsCandidate(m[1]);
            }
        }

        // For each candidate, also include the 6-digit prefix so prefix-matching works
        const allHsCandidates = [];
        for (const code of hsCandidates) {
            if (!allHsCandidates.includes(code)) allHsCandidates.push(code);
            if (code.length > 6) {
                const prefix6 = code.substring(0, 6);
                if (!allHsCandidates.includes(prefix6)) allHsCandidates.push(prefix6);
            }
        }

        // --- Collect chapter candidates — ONLY for codes that exist in the trade DB ---
        const chapterCandidates = [];
        const addChapterCandidate = (chapterValue) => {
            if (chapterValue === undefined || chapterValue === null) return;
            const chapterText = String(chapterValue).trim();
            const numeric = chapterText.replace(/\D/g, '');
            if (!numeric) return;
            const ch = numeric.padStart(2, '0').substring(0, 2);
            if (KNOWN_CHAPTERS.has(ch) && !chapterCandidates.includes(ch)) {
                chapterCandidates.push(ch);
            }
        };

        if (response.chapter) addChapterCandidate(response.chapter);

        const chapterContext = `${queryText || ''}\n${response.answer || ''}`;
        for (const m of chapterContext.matchAll(/\b(?:chapter|ch)\s*[-:]?\s*0?(\d{1,2})\b/gi)) {
            addChapterCandidate(m[1]);
        }

        for (const code of allHsCandidates) {
            const prefix6 = code.substring(0, 6);
            if (KNOWN_TRADE_CODES.has(prefix6)) {
                addChapterCandidate(prefix6.substring(0, 2));
            }
        }

        // Nothing to chart — exit silently
        if (hsCandidates.length === 0 && chapterCandidates.length === 0) {
            console.log('No HS code or chapter found for visualization');
            return;
        }

        // --- Insert chart card with loading spinner into the message bubble ---
        const chartId = `chart-${++chartCounter}`;
        const chartTitleId = `${chartId}-title`;
        const messageContent = msgDiv.querySelector('.message-content');

        const chartCard = document.createElement('div');
        chartCard.className = 'message-chart-card';
        chartCard.innerHTML = `
            <div class="message-chart-header">
                <div class="chart-header-label">
                    <span>Data</span>
                    <span class="chart-title-text" id="${chartTitleId}">Loading trade data…</span>
                </div>
                <div class="chart-tabs">
                    <button class="chart-tab-btn active" data-tab="chart">Chart</button>
                    <button class="chart-tab-btn" data-tab="table">Table</button>
                </div>
            </div>
            <div class="message-chart-body">
                <div class="message-chart-loading" id="${chartId}-loading">
                    <div class="chart-spinner"></div>
                    <span>Loading chart data…</span>
                </div>
                <div id="${chartId}-content" style="display:none;">
                    <div class="chart-tab-panel" id="${chartId}-panel-chart">
                        <div class="message-chart-canvas-wrap">
                            <canvas id="${chartId}"></canvas>
                        </div>
                    </div>
                    <div class="chart-tab-panel" id="${chartId}-panel-table" style="display:none;">
                        <div id="${chartId}-table"></div>
                    </div>
                </div>
            </div>
        `;

        // Tab switching
        chartCard.querySelectorAll('.chart-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                chartCard.querySelectorAll('.chart-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const tab = btn.dataset.tab;
                document.getElementById(`${chartId}-panel-chart`).style.display = tab === 'chart' ? 'block' : 'none';
                document.getElementById(`${chartId}-panel-table`).style.display = tab === 'table' ? 'block' : 'none';
            });
        });

        // Insert before the sources section if present, otherwise append
        const sourcesEl = messageContent.querySelector('.message-sources');
        if (sourcesEl) {
            messageContent.insertBefore(chartCard, sourcesEl);
        } else {
            messageContent.appendChild(chartCard);
        }

        scrollToBottom();

        const loadingEl = document.getElementById(`${chartId}-loading`);
        const contentEl = document.getElementById(`${chartId}-content`);
        const tableEl = document.getElementById(`${chartId}-table`);

        let chartRendered = false;

        // Helper: render monthly line chart + table
        function renderMonthly(monthlyData, label) {
            chartRendered = true;
            const titleEl = document.getElementById(chartTitleId);
            if (titleEl) titleEl.textContent = `Monthly Exports — HS ${label}`;
            if (tableEl) {
                tableEl.innerHTML = `
                    <p style="margin-bottom:0.4rem;font-size:0.82rem;color:var(--text-secondary);">
                        <strong>Monthly Export Trend (2024)</strong> — ${label}
                    </p>
                    ${createMonthlyDataTable(monthlyData)}
                    <p style="margin-top:0.4rem; font-size:0.75rem; color:var(--text-muted);">
                        Last Updated: ${new Date(monthlyData.timestamp).toLocaleString()}
                    </p>
                `;
            }
            if (loadingEl) loadingEl.style.display = 'none';
            if (contentEl) contentEl.style.display = 'block';
            setTimeout(() => createLineChart(monthlyData, label, chartId), 50);
        }

        // Helper: render annual bar chart + table
        function renderAnnual(data, label) {
            chartRendered = true;
            const titleEl = document.getElementById(chartTitleId);
            if (titleEl) titleEl.textContent = `Annual Exports — HS ${label}`;
            if (tableEl) {
                tableEl.innerHTML = `
                    <p style="margin-bottom:0.4rem;font-size:0.82rem;color:var(--text-secondary);">
                        <strong>Export Data by Country (Annual)</strong> — ${label}
                    </p>
                    ${createDataTable(data.data)}
                    <p style="margin-top:0.4rem; font-size:0.75rem; color:var(--text-muted);">
                        Last Updated: ${new Date(data.timestamp).toLocaleString()}
                    </p>
                `;
            }
            if (loadingEl) loadingEl.style.display = 'none';
            if (contentEl) contentEl.style.display = 'block';
            setTimeout(() => createBarChart(data.data, label, chartId), 50);
        }

        // --- Pass 1: Try HS codes — only those known to have data ---
        for (const hsCode of allHsCandidates) {
            if (chartRendered) break;
            if (!KNOWN_TRADE_CODES.has(hsCode.substring(0, 6))) {
                console.log(`HS ${hsCode}: not in trade dataset, skipping`);
                continue;
            }
            try {
                const d = await getMonthlyTradeData(hsCode, null);
                if (d.months?.length > 0 && Object.keys(d.monthly_data).length > 0) {
                    renderMonthly(d, hsCode); break;
                }
            } catch (e) { console.log(`Monthly HS ${hsCode}: ${e.message}`); }

            try {
                const d = await getTradeData(hsCode, null);
                if (d.data?.length > 0) {
                    renderAnnual(d, hsCode); break;
                }
            } catch (e) { console.log(`Annual HS ${hsCode}: ${e.message}`); }
        }

        // --- Pass 2: Try chapter-level queries ---
        if (!chartRendered) {
            for (const ch of chapterCandidates) {
                if (chartRendered) break;
                try {
                    const d = await getMonthlyTradeData(null, ch);
                    if (d.months?.length > 0 && Object.keys(d.monthly_data).length > 0) {
                        renderMonthly(d, `Chapter ${ch}`); break;
                    }
                } catch (e) { console.log(`Monthly chapter ${ch}: ${e.message}`); }

                try {
                    const d = await getTradeData(null, ch);
                    if (d.data?.length > 0) {
                        renderAnnual(d, `Chapter ${ch}`); break;
                    }
                } catch (e) { console.log(`Annual chapter ${ch}: ${e.message}`); }
            }
        }

        // --- No data found: remove the chart card entirely ---
        if (!chartRendered) {
            chartCard.remove();
        }

        scrollToBottom();

    } catch (error) {
        console.error('Error embedding chart in message:', error);
    }
}

function createDataTable(data) {
    if (!data || data.length === 0) return '<p>No data available</p>';

    const total = data.reduce((sum, item) => sum + item.value, 0);

    let html = `<table class="data-table"><thead><tr>
        <th>Country</th>
        <th style="text-align:right;">Export Value (₹ Crore)</th>
        <th style="text-align:right;">% Share</th>
    </tr></thead><tbody>`;

    data.forEach((item) => {
        const pct = total > 0 ? ((item.value / total) * 100).toFixed(1) : 0;
        html += `<tr>
            <td style="font-weight:500;">${item.country}</td>
            <td style="text-align:right;">₹${item.value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
            <td style="text-align:right;">${pct}%</td>
        </tr>`;
    });

    html += `</tbody><tfoot><tr>
        <td>Total</td>
        <td style="text-align:right;">₹${total.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
        <td style="text-align:right;">100%</td>
    </tr></tfoot></table>`;

    return html;
}

function createMonthlyDataTable(monthlyData) {
    const countries = Object.keys(monthlyData.monthly_data);
    const months = monthlyData.months;
    if (countries.length === 0 || months.length === 0) return '<p>No monthly data available</p>';

    let html = `<table class="data-table"><thead><tr>
        <th>Month</th>`;
    countries.forEach(c => {
        html += `<th style="text-align:right;">${c} (₹ Cr)</th>`;
    });
    html += `</tr></thead><tbody>`;

    months.forEach(monthName => {
        html += `<tr><td style="font-weight:500;">${monthName}</td>`;
        countries.forEach(country => {
            const entry = monthlyData.monthly_data[country].find(m => m.month_name === monthName);
            const val = entry ? entry.value : 0;
            const growth = entry && entry.growth_pct !== null ? entry.growth_pct : null;
            let growthBadge = '';
            if (growth !== null) {
                const color = growth >= 0 ? '#10b981' : '#ef4444';
                const arrow = growth >= 0 ? '▲' : '▼';
                growthBadge = ` <span style="font-size:0.75rem;color:${color};">${arrow}${Math.abs(growth).toFixed(1)}%</span>`;
            }
            html += `<td style="text-align:right;">₹${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${growthBadge}</td>`;
        });
        html += `</tr>`;
    });

    // Totals row
    html += `<tr style="font-weight:600;border-top:2px solid var(--border);"><td>Total</td>`;
    countries.forEach(country => {
        const total = monthlyData.monthly_data[country].reduce((s, m) => s + m.value, 0);
        html += `<td style="text-align:right;">₹${total.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>`;
    });
    html += `</tr></tbody></table>`;

    return html;
}

function createBarChart(data, label, canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    if (chartInstances[canvasId]) chartInstances[canvasId].destroy();

    // Dark theme chart colors
    const chartColors = [
        { bg: 'rgba(99, 102, 241, 0.7)', border: 'rgba(99, 102, 241, 1)' },
        { bg: 'rgba(16, 185, 129, 0.7)', border: 'rgba(16, 185, 129, 1)' },
        { bg: 'rgba(245, 158, 11, 0.7)', border: 'rgba(245, 158, 11, 1)' },
        { bg: 'rgba(239, 68, 68, 0.7)', border: 'rgba(239, 68, 68, 1)' },
        { bg: 'rgba(139, 92, 246, 0.7)', border: 'rgba(139, 92, 246, 1)' },
    ];

    chartInstances[canvasId] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(d => d.country),
            datasets: [{
                label: 'Export Value (Crore ₹)',
                data: data.map(d => d.value),
                backgroundColor: data.map((_, i) => chartColors[i % chartColors.length].bg),
                borderColor: data.map((_, i) => chartColors[i % chartColors.length].border),
                borderWidth: 2,
                borderRadius: 6,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                title: {
                    display: true,
                    text: `Export Statistics — HS ${label}`,
                    color: '#e8eaed',
                    font: { size: 15, weight: 'bold', family: 'Inter, sans-serif' },
                    padding: { bottom: 16 }
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif', size: 12 },
                        padding: 12
                    }
                },
                tooltip: {
                    backgroundColor: '#1c1f2e',
                    titleColor: '#e8eaed',
                    bodyColor: '#9aa0b0',
                    borderColor: '#2a2d3e',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 10,
                    callbacks: {
                        label: function (context) {
                            return ` ₹${context.parsed.y.toLocaleString('en-IN')} Cr`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Export Value (Crore ₹)',
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif', size: 12 }
                    },
                    ticks: {
                        color: '#5f6577',
                        font: { family: 'Inter, sans-serif' },
                        callback: (value) => '₹' + value.toLocaleString('en-IN')
                    },
                    grid: {
                        color: 'rgba(42, 45, 62, 0.6)',
                        drawBorder: false
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Country',
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif', size: 12 }
                    },
                    ticks: {
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif' }
                    },
                    grid: {
                        display: false
                    }
                }
            }
        }
    });
}

function createLineChart(monthlyData, label, canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    if (chartInstances[canvasId]) chartInstances[canvasId].destroy();

    const chartColors = [
        { bg: 'rgba(99, 102, 241, 0.15)', border: 'rgba(99, 102, 241, 1)' },
        { bg: 'rgba(16, 185, 129, 0.15)', border: 'rgba(16, 185, 129, 1)' },
        { bg: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 1)' },
    ];

    const countries = Object.keys(monthlyData.monthly_data);
    const months = monthlyData.months;

    const datasets = countries.map((country, i) => {
        const color = chartColors[i % chartColors.length];
        const values = months.map(mn => {
            const entry = monthlyData.monthly_data[country].find(m => m.month_name === mn);
            return entry ? entry.value : 0;
        });

        return {
            label: country,
            data: values,
            borderColor: color.border,
            backgroundColor: color.bg,
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 4,
            pointHoverRadius: 7,
            pointBackgroundColor: color.border,
            pointBorderColor: '#0f1117',
            pointBorderWidth: 2,
        };
    });

    chartInstances[canvasId] = new Chart(ctx, {
        type: 'line',
        data: { labels: months, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                title: {
                    display: true,
                    text: `Monthly Export Trend — HS ${label} (2024)`,
                    color: '#e8eaed',
                    font: { size: 15, weight: 'bold', family: 'Inter, sans-serif' },
                    padding: { bottom: 16 }
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif', size: 12 },
                        padding: 12,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                },
                tooltip: {
                    backgroundColor: '#1c1f2e',
                    titleColor: '#e8eaed',
                    bodyColor: '#9aa0b0',
                    borderColor: '#2a2d3e',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 10,
                    callbacks: {
                        label: function (context) {
                            return ` ${context.dataset.label}: ₹${context.parsed.y.toLocaleString('en-IN')} Cr`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Export Value (Crore ₹)',
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif', size: 12 }
                    },
                    ticks: {
                        color: '#5f6577',
                        font: { family: 'Inter, sans-serif' },
                        callback: (value) => '₹' + value.toLocaleString('en-IN')
                    },
                    grid: {
                        color: 'rgba(42, 45, 62, 0.6)',
                        drawBorder: false
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Month (2024)',
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif', size: 12 }
                    },
                    ticks: {
                        color: '#9aa0b0',
                        font: { family: 'Inter, sans-serif' }
                    },
                    grid: {
                        display: false
                    }
                }
            }
        }
    });
}

// === UTILITIES ===

function setLoading(isLoading) {
    sendBtn.disabled = isLoading;
    userInput.disabled = isLoading;

    const sendText = sendBtn.querySelector('.send-text');
    const sendIcon = sendBtn.querySelector('.send-icon');
    const spinner = sendBtn.querySelector('.loading-spinner');

    if (isLoading) {
        if (sendText) sendText.style.display = 'none';
        if (sendIcon) sendIcon.style.display = 'none';
        if (spinner) spinner.style.display = 'inline-flex';
    } else {
        if (sendText) sendText.style.display = '';
        if (sendIcon) sendIcon.style.display = '';
        if (spinner) spinner.style.display = 'none';
        userInput.focus();
    }
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// === ERROR HANDLING ===

window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
});
