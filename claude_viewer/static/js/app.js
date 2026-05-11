// Claude Code Viewer JavaScript

class ClaudeViewer {
    constructor() {
        this.liveSource = null;
        this.liveSessionId = null;
        this.liveAssistantContent = null;
        this.liveAssistantText = '';
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupCodeCopyButtons();
        this.setupSearch();
        this.setupSidebar();
        this.setupConversationScroll();
        this.setupLiveClaude();
    }

    setupEventListeners() {
        // Theme toggle
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.toggleTheme());
        }

        // Search form
        const searchForm = document.getElementById('search-form');
        if (searchForm) {
            searchForm.addEventListener('submit', (e) => this.handleSearch(e));
        }

        // Clear filters
        const clearBtn = document.getElementById('clear-filters');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => this.clearFilters());
        }

        // Auto-submit on filter change
        const filters = document.querySelectorAll('.auto-filter');
        filters.forEach(filter => {
            filter.addEventListener('change', () => this.autoSubmitFilters());
        });

        const sessionLinks = document.querySelectorAll('.session-link[target="conversation-frame"]');
        sessionLinks.forEach(link => {
            link.addEventListener('click', (event) => this.handleSessionClick(event, link));
        });

        const globalResults = document.querySelectorAll('[data-global-result][target="conversation-frame"]');
        globalResults.forEach(link => {
            link.addEventListener('click', (event) => this.handleGlobalResultClick(event, link));
        });

        const projectToggles = document.querySelectorAll('[data-project-toggle]');
        projectToggles.forEach(toggle => {
            toggle.addEventListener('click', () => this.toggleProject(toggle));
        });

        const revealButtons = document.querySelectorAll('[data-session-reveal]');
        revealButtons.forEach(button => {
            button.addEventListener('click', () => this.revealMoreSessions(button));
        });

        window.addEventListener('popstate', () => this.syncSessionFromUrl());
    }

    setActiveSession(activeLink) {
        const sessionLinks = document.querySelectorAll('.session-link[target="conversation-frame"]');
        sessionLinks.forEach(link => link.classList.remove('active'));
        activeLink.classList.add('active');
        activeLink.classList.remove('d-none');

        const group = activeLink.closest('[data-project-group]');
        if (group) {
            this.setProjectCollapsed(group, false);
        }
    }

    handleSessionClick(event, link) {
        const frame = document.querySelector('iframe[name="conversation-frame"]');
        if (!frame) {
            this.setActiveSession(link);
            return;
        }

        event.preventDefault();
        frame.src = link.href;
        this.setActiveSession(link);
        this.updateSessionUrl(link);
    }

    handleGlobalResultClick(event, resultLink) {
        const frame = document.querySelector('iframe[name="conversation-frame"]');
        if (!frame) return;

        event.preventDefault();
        frame.src = resultLink.href;

        const sidebarLink = this.findSessionLink(resultLink.dataset.project, resultLink.dataset.session);
        if (sidebarLink) {
            this.setActiveSession(sidebarLink);
        }

        this.updateSessionUrl(resultLink);
    }

    updateSessionUrl(link) {
        const project = link.dataset.project;
        const session = link.dataset.session;
        if (!project || !session) return;

        const url = new URL(window.location);
        url.pathname = '/';
        url.searchParams.set('project', project);
        url.searchParams.set('session', session);
        if (link.dataset.globalResult) {
            url.searchParams.set('q', new URL(link.href).searchParams.get('search') || '');
        }
        window.history.pushState({ project, session }, '', url);
    }

    setupSidebar() {
        const activeLink = document.querySelector('.session-link.active');
        if (activeLink) {
            this.setActiveSession(activeLink);
        }

        document.querySelectorAll('[data-session-reveal]').forEach(button => {
            this.updateRevealButton(button);
        });

        this.syncSessionFromUrl(false);
    }

    syncSessionFromUrl(updateFrame = true) {
        const params = new URLSearchParams(window.location.search);
        const project = params.get('project');
        const session = params.get('session');
        if (!project || !session) return;

        const link = this.findSessionLink(project, session);
        if (!link) return;

        this.setActiveSession(link);

        const frame = document.querySelector('iframe[name="conversation-frame"]');
        if (updateFrame && frame && frame.src !== link.href) {
            frame.src = link.href;
        }
    }

    findSessionLink(project, session) {
        if (!project || !session) return null;

        const selector = `.session-link[data-project="${CSS.escape(project)}"][data-session="${CSS.escape(session)}"]`;
        return document.querySelector(selector);
    }

    toggleProject(toggle) {
        const group = toggle.closest('[data-project-group]');
        if (!group) return;

        this.setProjectCollapsed(group, !group.classList.contains('collapsed'));
    }

    setProjectCollapsed(group, collapsed) {
        group.classList.toggle('collapsed', collapsed);
        const toggle = group.querySelector('[data-project-toggle]');
        if (toggle) {
            toggle.setAttribute('aria-expanded', String(!collapsed));
        }
    }

    revealMoreSessions(button) {
        const group = button.closest('[data-project-group]');
        if (!group) return;

        const hiddenSessions = Array.from(group.querySelectorAll('.session-extra.d-none'));
        hiddenSessions.slice(0, 4).forEach(link => link.classList.remove('d-none'));
        this.updateRevealButton(button);
    }

    updateRevealButton(button) {
        const group = button.closest('[data-project-group]');
        if (!group) return;

        const hiddenCount = group.querySelectorAll('.session-extra.d-none').length;
        button.hidden = hiddenCount === 0;
        button.textContent = hiddenCount > 4 ? 'Show 4 more' : `Show ${hiddenCount} more`;
    }

    setupCodeCopyButtons() {
        // Add copy buttons to all code blocks and pre elements
        const codeElements = document.querySelectorAll('.code-block, .message-content pre');
        
        codeElements.forEach(block => {
            // Skip if copy button already exists
            if (block.querySelector('.copy-btn')) return;
            
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.textContent = 'Copy';
            copyBtn.onclick = () => this.copyCode(block);
            
            // Make block relative positioned
            block.style.position = 'relative';
            block.appendChild(copyBtn);
        });
    }

    setupSearch() {
        // Setup search input with debounce
        const searchInput = document.getElementById('search');
        if (searchInput) {
            let debounceTimer;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    if (e.target.value.length > 2 || e.target.value.length === 0) {
                        this.autoSubmitFilters();
                    }
                }, 500);
            });
        }
    }

    setupConversationScroll() {
        const messagesContainer = document.querySelector('.messages-container');
        if (!messagesContainer || window.location.hash) return;

        requestAnimationFrame(() => {
            window.scrollTo({
                top: document.documentElement.scrollHeight,
                behavior: 'auto'
            });
        });
    }

    setupLiveClaude() {
        const form = document.getElementById('live-claude-form');
        if (!form) return;

        form.addEventListener('submit', (event) => this.startLiveClaude(event));
    }

    async startLiveClaude(event) {
        event.preventDefault();

        const input = document.getElementById('live-claude-prompt');
        const prompt = input?.value.trim();
        if (!prompt) return;

        this.closeLiveSource();
        this.showLivePanel(prompt);
        this.setLiveStatus('starting');

        try {
            const response = await fetch('/api/live/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt,
                    session_id: this.liveSessionId,
                }),
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Unable to start Claude');
            }

            const job = await response.json();
            if (job.session_id) {
                this.liveSessionId = job.session_id;
                this.setLiveSession(job.session_id);
            }
            this.openLiveStream(job.stream_url);
            input.value = '';
        } catch (error) {
            this.setLiveStatus(error.message || 'failed');
            this.appendLiveSystemMessage(error.message || 'Unable to start Claude');
        }
    }

    openLiveStream(streamUrl) {
        const source = new EventSource(streamUrl);
        this.liveSource = source;

        source.addEventListener('init', (event) => {
            const data = this.parseLiveEvent(event);
            if (data?.session_id) {
                this.liveSessionId = data.session_id;
                this.setLiveSession(data.session_id);
            }
            this.setLiveStatus(data?.model ? `running / ${data.model}` : 'running');
        });

        source.addEventListener('status', (event) => {
            const data = this.parseLiveEvent(event);
            if (data?.session_id) {
                this.liveSessionId = data.session_id;
                this.setLiveSession(data.session_id);
            }
            if (data?.status) {
                this.setLiveStatus(data.status);
            }
        });

        source.addEventListener('assistant_start', () => {
            this.ensureLiveAssistantMessage();
        });

        source.addEventListener('delta', (event) => {
            const data = this.parseLiveEvent(event);
            this.appendLiveAssistantDelta(data?.text || '');
        });

        source.addEventListener('raw', (event) => {
            const data = this.parseLiveEvent(event);
            if (data?.text) {
                this.appendLiveSystemMessage(data.text);
            }
        });

        source.addEventListener('result', (event) => {
            const data = this.parseLiveEvent(event);
            if (data?.session_id) {
                this.liveSessionId = data.session_id;
                this.setLiveSession(data.session_id);
            }
            this.setLiveStatus(data?.status || 'complete');
        });

        source.addEventListener('done', (event) => {
            const data = this.parseLiveEvent(event);
            this.setLiveStatus(data?.status || 'done');
            this.closeLiveSource();
            if (data?.session_id) {
                this.liveSessionId = data.session_id;
                this.setLiveSession(data.session_id);
            }
            if (data?.conversation_url) {
                setTimeout(() => this.showPersistedConversation(data), 900);
            }
        });

        source.addEventListener('error', () => {
            if (source.readyState === EventSource.CLOSED) return;
            this.setLiveStatus('stream interrupted');
        });
    }

    parseLiveEvent(event) {
        try {
            return JSON.parse(event.data || '{}');
        } catch {
            return {};
        }
    }

    showLivePanel(prompt) {
        const panel = document.getElementById('live-claude-panel');
        const frame = document.getElementById('conversation-frame');
        const messages = document.getElementById('live-claude-messages');
        if (!panel || !messages) return;

        panel.classList.remove('d-none');
        if (frame) frame.classList.add('d-none');
        messages.innerHTML = '';
        this.liveAssistantContent = null;
        this.liveAssistantText = '';
        this.appendLiveMessage('user', 'User', prompt);
        this.ensureLiveAssistantMessage();
        this.scrollLivePanel();
    }

    appendLiveMessage(role, label, text) {
        const messages = document.getElementById('live-claude-messages');
        if (!messages) return null;

        const message = document.createElement('div');
        message.className = `live-message ${role}`;

        const header = document.createElement('div');
        header.className = 'live-message-header';
        header.textContent = label;

        const content = document.createElement('div');
        content.className = 'live-message-content';
        content.textContent = text;

        message.append(header, content);
        messages.appendChild(message);
        this.scrollLivePanel();
        return content;
    }

    ensureLiveAssistantMessage() {
        if (this.liveAssistantContent) return;

        this.liveAssistantContent = this.appendLiveMessage('assistant', 'Claude', '');
    }

    appendLiveAssistantDelta(text) {
        if (!text) return;

        this.ensureLiveAssistantMessage();
        this.liveAssistantText += text;
        this.liveAssistantContent.textContent = this.liveAssistantText;
        this.scrollLivePanel();
    }

    appendLiveSystemMessage(text) {
        this.appendLiveMessage('system', 'System', text);
    }

    setLiveStatus(status) {
        const statusEl = document.getElementById('live-claude-status');
        if (statusEl) {
            statusEl.textContent = status;
        }
    }

    setLiveSession(sessionId) {
        const sessionEl = document.getElementById('live-claude-session');
        if (sessionEl) {
            sessionEl.textContent = `Session ${sessionId.slice(0, 8)}...`;
        }
    }

    showPersistedConversation(data) {
        const panel = document.getElementById('live-claude-panel');
        const frame = document.getElementById('conversation-frame');
        if (!frame || !data.conversation_url) return;

        frame.src = data.conversation_url;
        frame.classList.remove('d-none');
        if (panel) panel.classList.add('d-none');

        const url = new URL(window.location);
        url.pathname = '/';
        if (data.project_name) url.searchParams.set('project', data.project_name);
        if (data.session_id) url.searchParams.set('session', data.session_id);
        window.history.pushState({
            project: data.project_name,
            session: data.session_id,
        }, '', url);
    }

    scrollLivePanel() {
        const messages = document.getElementById('live-claude-messages');
        if (messages) {
            messages.scrollTop = messages.scrollHeight;
        }
    }

    closeLiveSource() {
        if (this.liveSource) {
            this.liveSource.close();
            this.liveSource = null;
        }
    }

    toggleTheme() {
        const body = document.body;
        const isDark = body.classList.contains('dark-theme');
        
        if (isDark) {
            body.classList.remove('dark-theme');
            localStorage.setItem('theme', 'light');
        } else {
            body.classList.add('dark-theme');
            localStorage.setItem('theme', 'dark');
        }
    }

    copyCode(codeBlock) {
        // Get the code content - handle both .code-block and direct pre elements
        let code;
        if (codeBlock.tagName === 'PRE') {
            code = codeBlock.textContent;
        } else {
            const preElement = codeBlock.querySelector('pre');
            code = preElement ? preElement.textContent : codeBlock.textContent;
        }
        
        if (navigator.clipboard) {
            navigator.clipboard.writeText(code).then(() => {
                this.showCopyFeedback(codeBlock);
            });
        } else {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = code;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            this.showCopyFeedback(codeBlock);
        }
    }

    showCopyFeedback(codeBlock) {
        const copyBtn = codeBlock.querySelector('.copy-btn');
        const originalText = copyBtn.textContent;
        
        copyBtn.textContent = 'Copied!';
        copyBtn.style.background = 'rgba(16, 185, 129, 0.2)';
        
        setTimeout(() => {
            copyBtn.textContent = originalText;
            copyBtn.style.background = '';
        }, 2000);
    }

    handleSearch(e) {
        e.preventDefault();
        const formData = new FormData(e.target);
        const params = new URLSearchParams();
        
        for (let [key, value] of formData.entries()) {
            if (value.trim()) {
                params.append(key, value.trim());
            }
        }
        
        // Redirect with search parameters
        const url = new URL(window.location);
        url.search = params.toString();
        window.location.href = url.toString();
    }

    autoSubmitFilters() {
        const form = document.getElementById('search-form');
        if (form) {
            form.submit();
        }
    }

    clearFilters() {
        // Clear all form inputs
        const form = document.getElementById('search-form');
        if (form) {
            form.reset();
            
            // Remove URL parameters and redirect
            const url = new URL(window.location);
            if (document.body.classList.contains('embedded-view')) {
                url.search = 'embedded=true';
            } else {
                url.search = '';
            }
            window.location.href = url.toString();
        }
    }

    // Utility methods
    formatFileSize(bytes) {
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        if (bytes === 0) return '0 Bytes';
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
    }

    formatDate(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        
        if (diffDays === 0) {
            return 'Today';
        } else if (diffDays === 1) {
            return 'Yesterday';
        } else if (diffDays < 7) {
            return `${diffDays} days ago`;
        } else {
            return date.toLocaleDateString();
        }
    }

    // Search highlighting
    highlightSearchTerms(text, searchTerm) {
        if (!searchTerm) return text;
        
        const regex = new RegExp(`(${searchTerm})`, 'gi');
        return text.replace(regex, '<mark>$1</mark>');
    }

    // Smooth scroll to element
    scrollToElement(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth' });
        }
    }

    // Show loading state
    showLoading(element) {
        if (element) {
            element.innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    Loading...
                </div>
            `;
        }
    }

    // Initialize pagination
    setupPagination() {
        const paginationLinks = document.querySelectorAll('.pagination .page-link');
        paginationLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const url = new URL(link.href);
                this.loadPage(url.searchParams.get('page'));
            });
        });
    }

    loadPage(pageNumber) {
        const url = new URL(window.location);
        url.searchParams.set('page', pageNumber);
        window.location.href = url.toString();
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Load saved theme
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
    }

    // Initialize the main app
    window.claudeViewer = new ClaudeViewer();
    
    // Setup pagination if present
    window.claudeViewer.setupPagination();
});

// Utility functions for templates
window.formatFileSize = (bytes) => {
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    if (bytes === 0) return '0 Bytes';
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
};

window.formatRelativeTime = (dateString) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) {
        return 'Today';
    } else if (diffDays === 1) {
        return 'Yesterday';
    } else if (diffDays < 7) {
        return `${diffDays} days ago`;
    } else {
        return date.toLocaleDateString();
    }
};
