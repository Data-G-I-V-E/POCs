// ================================================
// Export Advisory System — Frontend JavaScript
// ================================================

// === CONFIG ===
const API_BASE = window.location.origin;
let currentSessionId = localStorage.getItem('export_session_id') || 'default';
let tradeChart = null;
let monthlyChart = null;

// === DOM ELEMENTS ===
const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const newSessionBtn = document.getElementById('new-session-btn');
const clearSessionBtn = document.getElementById('clear-session-btn');
const sessionDisplay = document.getElementById('session-display');
const chartContainer = document.getElementById('chart-container');
const chartInfo = document.getElementById('chart-info');
const chartDetails = document.getElementById('chart-details');
const closeVizBtn = document.getElementById('close-viz-btn');

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

    if (closeVizBtn) {
        closeVizBtn.addEventListener('click', () => {
            const vizSection = document.getElementById('viz-section');
            if (vizSection) vizSection.style.display = 'none';
        });
    }

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

        addSystemMessage(`📝 Restored ${data.message_count} messages from previous session`);
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
        <div class="message-header">🤖 Assistant</div>
        <div class="message-content">
            ${formattedAnswer}
            <div class="message-meta">
                <span class="meta-tag">📂 Restored</span>
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
            addSystemMessage('⚠️ Server is not fully initialized. Some features may not work.');
        }
    } catch (error) {
        console.error('Health check failed:', error);
        addSystemMessage('❌ Cannot connect to server. Please check if the backend is running.');
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

        // Add assistant response
        addAssistantMessage(response);

        // Check if we should show visualization
        if (shouldShowVisualization(query, response)) {
            await updateVisualization(response);
        }

    } catch (error) {
        console.error('Error sending message:', error);
        addSystemMessage(`❌ Error: ${error.message}`);
    } finally {
        setLoading(false);
    }
}

function addUserMessage(content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-user';
    messageDiv.innerHTML = `
        <div class="message-header">👤 You</div>
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
                <h4>📚 Sources</h4>
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
        metaHtml += `<span class="meta-tag">🌍 ${response.country.toUpperCase()}</span>`;
    }
    metaHtml += `<span class="meta-tag">${new Date(response.timestamp).toLocaleTimeString()}</span>`;
    metaHtml += '</div>';

    messageDiv.innerHTML = `
        <div class="message-header">
            🤖 Assistant
        </div>
        <div class="message-content">
            ${formattedAnswer}
            ${sourcesHtml}
            ${metaHtml}
        </div>
    `;

    chatMessages.appendChild(messageDiv);
    scrollToBottom();
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
        'sql': '📊 Data Query',
        'policy': '📋 Policy Check',
        'vector': '🔍 Document Search',
        'general': '💬 General',
        'combined': '🔗 Multi-Agent',
        'agreements': '📜 Agreements',
        'hs_lookup': '🔎 HS Lookup'
    };
    return labels[type] || `📌 ${type}`;
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
        return `${source.store || 'vector'} (${source.num_results || '?'} results)`;
    } else if (source.type === 'hs_master_lookup') {
        const ambig = source.is_ambiguous ? ' (AMBIGUOUS)' : '';
        return `${source.matches_found || 0} matches for "${source.search_term || '?'}"${ambig}`;
    } else if (source.type === 'trade_agreements') {
        const agreements = source.agreements?.join(', ') || 'N/A';
        return `${source.num_results || '?'} results from ${agreements}`;
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

    // Hide viz
    const vizSection = document.getElementById('viz-section');
    if (vizSection) vizSection.style.display = 'none';

    addSystemMessage(`✨ Started new session: ${sessionId}`);
}

async function handleClearSession() {
    if (!confirm('Clear conversation history for this session?')) return;

    try {
        await clearSession(currentSessionId);
        chatMessages.innerHTML = '';

        const vizSection = document.getElementById('viz-section');
        if (vizSection) vizSection.style.display = 'none';

        // Reset to default session
        currentSessionId = 'default';
        localStorage.setItem('export_session_id', 'default');
        sessionDisplay.textContent = 'Session: default';

        addSystemMessage('🧹 Session cleared successfully');
    } catch (error) {
        console.error('Error clearing session:', error);
        addSystemMessage(`❌ Error clearing session: ${error.message}`);
    }
}

// === VISUALIZATION ===

function shouldShowVisualization(query, response) {
    const hasSqlResults = response.query_type === 'sql' ||
        response.query_type === 'combined' ||
        response.sources?.some(s => s.type === 'sql');
    const hasHsCode = response.hs_code != null;

    // Keywords suggesting trade data visualization
    const vizKeywords = [
        'statistic', 'trade data', 'export value', 'export data',
        'chart', 'graph', 'trend', 'data', 'monthly', 'quarterly',
        'export', 'import', 'trade', 'restriction', 'can i export'
    ];
    const queryLower = query.toLowerCase();
    const queryWantsViz = vizKeywords.some(kw => queryLower.includes(kw));

    // Always show viz for combined/sql routes with an HS code
    if (hasHsCode && hasSqlResults) return true;

    return (hasSqlResults || hasHsCode) && (hasSqlResults || queryWantsViz);
}

async function updateVisualization(response) {
    try {
        const vizSection = document.getElementById('viz-section');
        const placeholder = document.getElementById('chart-placeholder');
        const canvas = document.getElementById('trade-chart');

        // Show section, reset state
        if (vizSection) vizSection.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
        if (canvas) canvas.style.display = 'block';
        chartInfo.style.display = 'block';

        // --- Collect HS code candidates (6-8 digit) ---
        const hsCandidates = [];

        if (response.hs_code) hsCandidates.push(response.hs_code);

        if (response.answer) {
            // Match standalone 6-8 digit numbers (word boundary prevents partial matches)
            for (const m of response.answer.matchAll(/\b(\d{6,8})\b/g)) {
                const code = m[1];
                if (!code.startsWith('202') && !code.startsWith('201') &&
                    !code.startsWith('200') && !hsCandidates.includes(code)) {
                    hsCandidates.push(code);
                }
            }
        }

        // --- Collect chapter candidates (2-digit, e.g. "07", "08") ---
        const chapterCandidates = [];

        // Derive chapters from every HS code collected
        for (const code of hsCandidates) {
            if (code.length >= 2) {
                const ch = code.substring(0, 2);
                if (!chapterCandidates.includes(ch)) chapterCandidates.push(ch);
            }
        }

        // Also extract chapters from "Chapter X" / "Ch. X" mentions in the answer
        if (response.answer) {
            for (const m of response.answer.matchAll(/\b(?:chapter|ch\.?)\s*(\d{1,2})\b/gi)) {
                const ch = m[1].padStart(2, '0');
                if (!chapterCandidates.includes(ch)) chapterCandidates.push(ch);
            }
        }

        if (hsCandidates.length === 0 && chapterCandidates.length === 0) {
            console.log('No HS code or chapter found for visualization');
            if (vizSection) vizSection.style.display = 'none';
            return;
        }

        let chartRendered = false;

        // Helper: render monthly chart + details table
        function renderMonthly(monthlyData, label) {
            chartRendered = true;
            chartDetails.innerHTML = `
                <p><strong>HS Code / Chapter:</strong> ${label}</p>
                <p style="margin-bottom:0.5rem;"><strong>Monthly Export Trend (2024):</strong></p>
                ${createMonthlyDataTable(monthlyData, label)}
                <p style="margin-top:0.5rem; font-size:0.8rem; color:var(--text-muted);">
                    Last Updated: ${new Date(monthlyData.timestamp).toLocaleString()}
                </p>
            `;
            // Delay chart creation so the browser can lay out the container first
            setTimeout(() => createLineChart(monthlyData, label), 50);
        }

        // Helper: render annual bar chart + details table
        function renderAnnual(data, label) {
            chartRendered = true;
            chartDetails.innerHTML = `
                <p><strong>HS Code / Chapter:</strong> ${label}</p>
                <p style="margin-bottom:0.5rem;"><strong>Export Data by Country (Annual):</strong></p>
                ${createDataTable(data.data, label)}
                <p style="margin-top:0.5rem; font-size:0.8rem; color:var(--text-muted);">
                    Last Updated: ${new Date(data.timestamp).toLocaleString()}
                </p>
            `;
            setTimeout(() => createBarChart(data.data, label), 50);
        }

        // --- Pass 1: Try exact HS codes ---
        for (const hsCode of hsCandidates) {
            if (chartRendered) break;
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

        // --- Pass 2: Try chapter-level queries (uses proper 'chapter' param) ---
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

        // --- No data found ---
        if (!chartRendered) {
            if (canvas) canvas.style.display = 'none';
            if (placeholder) {
                placeholder.style.display = 'flex';
                const tried = [
                    ...hsCandidates.map(c => `HS ${c}`),
                    ...chapterCandidates.map(c => `Ch.${c}`)
                ];
                placeholder.innerHTML = `
                    <p style="font-size:1.1rem;">📊 No chart data available</p>
                    <p class="chart-hint">
                        Tried: ${tried.slice(0, 6).join(', ')}${tried.length > 6 ? '...' : ''}<br>
                        Charts are available for the 31 focus HS codes tracked in the system.<br>
                        Detailed statistics are shown in the answer above.
                    </p>
                `;
            }
            chartDetails.innerHTML = '';
            chartInfo.style.display = 'none';
        }

        vizSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    } catch (error) {
        console.error('Error updating visualization:', error);
    }
}

function createDataTable(data, hsCode) {
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

function createMonthlyDataTable(monthlyData, hsCode) {
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

function createBarChart(data, hsCode) {
    const canvas = document.getElementById('trade-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    if (tradeChart) tradeChart.destroy();

    // Dark theme chart colors
    const chartColors = [
        { bg: 'rgba(99, 102, 241, 0.7)', border: 'rgba(99, 102, 241, 1)' },
        { bg: 'rgba(16, 185, 129, 0.7)', border: 'rgba(16, 185, 129, 1)' },
        { bg: 'rgba(245, 158, 11, 0.7)', border: 'rgba(245, 158, 11, 1)' },
        { bg: 'rgba(239, 68, 68, 0.7)', border: 'rgba(239, 68, 68, 1)' },
        { bg: 'rgba(139, 92, 246, 0.7)', border: 'rgba(139, 92, 246, 1)' },
    ];

    tradeChart = new Chart(ctx, {
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
                    text: `Export Statistics — HS ${hsCode}`,
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

function createLineChart(monthlyData, hsCode) {
    const canvas = document.getElementById('trade-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    if (tradeChart) tradeChart.destroy();
    if (monthlyChart) monthlyChart.destroy();

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

    monthlyChart = new Chart(ctx, {
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
                    text: `Monthly Export Trend — HS ${hsCode} (2024)`,
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

    // Keep reference so we can destroy it later
    tradeChart = monthlyChart;
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
