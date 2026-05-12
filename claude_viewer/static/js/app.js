// cocoview

class ClaudeViewer {
    constructor() {
        this.liveSource = null;
        this.liveSessionId = null;
        this.liveAssistantContent = null;
        this.liveAssistantText = '';
        this.activityRevision = null;
        this.activeSessionRevision = null;
        this.activeLiveStatus = null;
        this.activityTimer = null;
        this.shareTimer = null;
        this.didInitialConversationScroll = false;
        this.init();
    }

    init() {
        this.applyTheme(this.getSavedTheme());
        this.setupEventListeners();
        this.setupCodeCopyButtons();
        this.setupSearch();
        this.setupSidebar();
        this.setupConversationScroll();
        this.setupSessionShare();
        this.setupLiveClaude();
        this.setupActivityPolling();
        this.setupMobileSidebar();
        this.setupMobileGlobalSearch();
    }

    setupEventListeners() {
        // Theme toggle
        document.querySelectorAll('[data-theme-toggle]').forEach(toggle => {
            toggle.addEventListener('click', () => this.toggleTheme());
        });

        const frame = document.querySelector('iframe[name="conversation-frame"]');
        if (frame) {
            frame.addEventListener('load', () => {
                this.syncFrameTheme();
                // After the iframe's own JS auto-scrolls its content, iOS Safari can leave
                // the iframe GPU layer blank. Toggling opacity forces a GPU re-composite.
                setTimeout(() => {
                    frame.style.opacity = '0.9999';
                    requestAnimationFrame(() => { frame.style.opacity = ''; });
                }, 350);
            });
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

        const globalResults = document.querySelectorAll('[data-global-result][target="conversation-frame"]');
        globalResults.forEach(link => {
            link.addEventListener('click', (event) => this.handleGlobalResultClick(event, link));
        });

        document.addEventListener('submit', (event) => {
            const form = event.target.closest?.('[data-session-send-form]');
            if (form) {
                this.handleSessionSend(event, form);
            }
        });

        this.bindSidebarControls(document);

        window.addEventListener('popstate', () => this.syncSessionFromUrl());
    }

    bindSidebarControls(root) {
        const sessionLinks = root.querySelectorAll('.session-link[target="conversation-frame"]');
        sessionLinks.forEach(link => {
            link.addEventListener('click', (event) => this.handleSessionClick(event, link));
        });

        const projectToggles = root.querySelectorAll('[data-project-toggle]');
        projectToggles.forEach(toggle => {
            toggle.addEventListener('click', () => this.toggleProject(toggle));
        });

        const revealButtons = root.querySelectorAll('[data-session-reveal]');
        revealButtons.forEach(button => {
            button.addEventListener('click', () => this.revealMoreSessions(button));
        });
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

        this.syncMobileGlobalSearchScope();
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
        const currentParams = new URLSearchParams(window.location.search);
        const linkUrl = new URL(link.href, window.location.origin);
        url.pathname = '/';
        url.search = '';
        url.searchParams.set('project', project);
        url.searchParams.set('session', session);

        if (link.dataset.globalResult || link.dataset.searchResultSession) {
            const search = linkUrl.searchParams.get('highlight') || linkUrl.searchParams.get('search') || '';
            if (search) url.searchParams.set('q', search);

            const line = link.dataset.line || linkUrl.searchParams.get('line') || '';
            if (line) url.searchParams.set('line', line);

            const messageType = linkUrl.searchParams.get('message_type');
            if (messageType) url.searchParams.set('role', messageType);

            ['project_filter', 'date_from', 'date_to', 'has_code', 'has_errors', 'has_tools', 'has_file_edits'].forEach(key => {
                const value = currentParams.get(key);
                if (value) url.searchParams.set(key, value);
            });

            if (linkUrl.searchParams.get('show_tools') === 'true' && !url.searchParams.has('has_tools')) {
                url.searchParams.set('has_tools', '1');
            }
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
        if (!messagesContainer || this.didInitialConversationScroll) return;

        this.didInitialConversationScroll = true;

        const target = this.getConversationScrollTarget();
        if (target) {
            requestAnimationFrame(() => {
                target.scrollIntoView({ block: 'center', behavior: 'auto' });
            });
            return;
        }

        const params = new URLSearchParams(window.location.search);
        if (params.get('search') || params.get('highlight')) return;

        // Double-rAF + scrollIntoView: most reliable on iOS Safari inside iframes.
        // scrollIntoView triggers a native scroll which the browser paints correctly,
        // unlike direct scrollTop assignment which can leave content blank.
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                const lastMsg = document.querySelector('.messages-container .terminal-turn:last-child');
                if (lastMsg) {
                    lastMsg.scrollIntoView({ block: 'end', behavior: 'auto' });
                } else {
                    const scrollEl = document.scrollingElement || document.documentElement;
                    scrollEl.scrollTop = scrollEl.scrollHeight;
                }
                // Reading offsetHeight forces a synchronous layout commit, ensuring
                // iOS Safari rasterizes the newly visible content before yielding.
                void document.body.offsetHeight;
            });
        });
    }

    getConversationScrollTarget() {
        if (window.location.hash) {
            const hashId = window.location.hash.slice(1);
            const targetId = hashId ? decodeURIComponent(hashId) : '';
            const target = targetId ? document.getElementById(targetId) : null;
            if (target) return target;
        }

        const conversationView = document.querySelector('.conversation-view');
        const targetLine = conversationView?.dataset.targetLine;
        if (targetLine) {
            return document.getElementById(`message-line-${targetLine}`);
        }

        return document.querySelector('.terminal-turn.search-target');
    }

    setupMobileSidebar() {
        const overlay = document.getElementById('sidebar-overlay');
        const sidebar = document.querySelector('.session-sidebar');
        if (!sidebar) return;

        this._mobileSidebarOverlay = overlay;
        this._mobileSidebarOpen = () => {
            const s = document.querySelector('.session-sidebar');
            s?.classList.add('mobile-open');
            overlay?.classList.add('active');
            document.body.classList.add('mobile-sidebar-open');
            document.body.style.overflow = 'hidden';
            this.syncMobileGlobalSearchScope();
        };
        this._mobileSidebarClose = () => {
            const s = document.querySelector('.session-sidebar');
            s?.classList.remove('mobile-open');
            overlay?.classList.remove('active');
            document.body.classList.remove('mobile-sidebar-open');
            document.body.style.overflow = '';
            this.syncMobileGlobalSearchScope();
        };

        const toggle = () => {
            const s = document.querySelector('.session-sidebar');
            s?.classList.contains('mobile-open') ? this._mobileSidebarClose() : this._mobileSidebarOpen();
        };

        document.getElementById('sidebar-toggle-btn')?.addEventListener('click', toggle);
        overlay?.addEventListener('click', this._mobileSidebarClose);

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const s = document.querySelector('.session-sidebar');
                if (s?.classList.contains('mobile-open')) this._mobileSidebarClose();
            }
        });

        this.rebindMobileSidebar(sidebar);
    }

    setupMobileGlobalSearch() {
        const form = document.querySelector('.global-search-form');
        const filterToggle = document.getElementById('mobile-global-filter-toggle');
        const projectSelect = form?.querySelector('select[name="project_filter"]');
        if (!form) return;

        const params = new URLSearchParams(window.location.search);
        form.dataset.mobileProjectDefault = params.has('project_filter') ? 'false' : 'true';

        filterToggle?.addEventListener('click', () => {
            const isOpen = form.classList.toggle('mobile-filters-open');
            filterToggle.setAttribute('aria-expanded', String(isOpen));
        });

        projectSelect?.addEventListener('change', () => {
            form.dataset.mobileProjectDefault = 'false';
            this.syncMobileGlobalSearchScope();
        });

        document.addEventListener('click', (event) => {
            if (!form.classList.contains('mobile-filters-open')) return;
            if (form.contains(event.target) || filterToggle?.contains(event.target)) return;
            form.classList.remove('mobile-filters-open');
            filterToggle?.setAttribute('aria-expanded', 'false');
        });

        window.addEventListener('resize', () => this.syncMobileGlobalSearchScope());
        this.syncMobileGlobalSearchScope();
    }

    syncMobileGlobalSearchScope() {
        const form = document.querySelector('.global-search-form');
        if (!form || window.innerWidth > 768) return;

        const projectSelect = form.querySelector('select[name="project_filter"]');
        const searchInput = form.querySelector('.global-search-input');
        const activeProject = document.querySelector('.session-link.active')?.dataset.project || form.dataset.currentProject || '';
        const sidebarOpen = document.querySelector('.session-sidebar')?.classList.contains('mobile-open');

        if (projectSelect && form.dataset.mobileProjectDefault !== 'false') {
            projectSelect.value = sidebarOpen ? '' : activeProject;
        }

        const searchingAllProjects = !projectSelect?.value || sidebarOpen;
        if (searchInput) {
            searchInput.placeholder = searchingAllProjects
                ? 'Search all projects...'
                : 'Search current project...';
        }
    }

    rebindMobileSidebar(sidebar) {
        if (!sidebar) return;
        sidebar.addEventListener('click', (e) => {
            const link = e.target.closest('.session-link');
            if (link && window.innerWidth <= 768) this._mobileSidebarClose?.();
        });
        document.getElementById('sidebar-close-btn')?.addEventListener('click', () => this._mobileSidebarClose?.());
    }

    setupLiveClaude() {
        const form = document.getElementById('live-claude-form');
        if (!form) return;

        form.addEventListener('submit', (event) => this.startLiveClaude(event));
    }

    setupActivityPolling() {
        if (!document.querySelector('.sessions-page') && !document.querySelector('.conversation-view')) return;

        this.pollActivity();
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.pollActivity(true);
            }
        });
    }

    scheduleActivityPoll() {
        window.clearTimeout(this.activityTimer);
        const delay = document.hidden ? 30000 : 6000;
        this.activityTimer = window.setTimeout(() => this.pollActivity(), delay);
    }

    async pollActivity(runImmediately = false) {
        window.clearTimeout(this.activityTimer);

        try {
            const active = this.getActiveSessionInfo();
            const params = new URLSearchParams();
            if (active.project) params.set('project', active.project);
            if (active.session) params.set('session', active.session);

            const response = await fetch(`/api/activity?${params.toString()}`, {
                cache: 'no-store',
            });
            if (!response.ok) throw new Error('Activity check failed');

            const snapshot = await response.json();
            const firstRun = this.activityRevision === null;
            const changed = !firstRun && snapshot.revision !== this.activityRevision;
            const activeRevision = snapshot.active_session?.revision || null;
            const activeLiveStatus = snapshot.active_live_terminal?.status || null;
            const displayedRevision = this.getDisplayedConversationRevision();
            const activeChanged = Boolean(
                activeRevision &&
                (
                    (this.activeSessionRevision && activeRevision !== this.activeSessionRevision) ||
                    (displayedRevision && activeRevision !== displayedRevision)
                )
            );
            const activeLiveChanged = !firstRun && activeLiveStatus !== this.activeLiveStatus;

            this.activityRevision = snapshot.revision;
            this.activeSessionRevision = activeRevision;
            this.activeLiveStatus = activeLiveStatus;

            if (changed && document.querySelector('.sessions-page')) {
                await this.refreshSidebarHtml();
            }

            if (activeChanged || activeLiveChanged || (runImmediately && changed)) {
                this.refreshConversationFrame({ preserveScroll: true });
            }
        } catch (error) {
            // Keep polling quiet; this is a convenience path, not core navigation.
        } finally {
            this.scheduleActivityPoll();
        }
    }

    getActiveSessionInfo() {
        const params = new URLSearchParams(window.location.search);
        const activeLink = document.querySelector('.session-link.active');
        const conversationView = document.querySelector('.conversation-view');

        return {
            project: params.get('project') || activeLink?.dataset.project || conversationView?.dataset.project || '',
            session: params.get('session') || activeLink?.dataset.session || conversationView?.dataset.session || '',
        };
    }

    getDisplayedConversationRevision() {
        const frame = document.querySelector('iframe[name="conversation-frame"]');
        if (frame?.contentDocument) {
            const framedView = frame.contentDocument.querySelector('.conversation-view');
            if (framedView?.dataset.fileRevision) {
                return framedView.dataset.fileRevision;
            }
        }

        const conversationView = document.querySelector('.conversation-view');
        return conversationView?.dataset.fileRevision || null;
    }

    async refreshSidebarHtml() {
        const currentSidebar = document.querySelector('.session-sidebar');
        if (!currentSidebar) return;

        const response = await fetch(window.location.href, { cache: 'no-store' });
        if (!response.ok) return;

        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const nextSidebar = doc.querySelector('.session-sidebar');
        if (!nextSidebar) return;

        const wasOpen = currentSidebar.classList.contains('mobile-open');
        currentSidebar.replaceWith(nextSidebar);
        if (wasOpen) nextSidebar.classList.add('mobile-open');
        this.bindSidebarControls(nextSidebar);
        this.setupSidebar();
        this.rebindMobileSidebar(nextSidebar);
    }

    refreshConversationFrame(options = {}) {
        const panel = document.getElementById('live-claude-panel');
        if (panel && !panel.classList.contains('d-none')) return;

        const frame = document.querySelector('iframe[name="conversation-frame"]');
        if (!frame || !frame.src) {
            this.refreshConversationHtml({ preserveScroll: true, ...options });
            return;
        }

        const childViewer = frame.contentWindow?.claudeViewer;
        if (childViewer?.refreshConversationHtml) {
            childViewer.refreshConversationHtml({ preserveScroll: true, ...options });
            return;
        }

        // Last-resort fallback for cross-origin or not-yet-initialized frames.
        // This should be rare; the normal path updates the iframe DOM in place.
        const url = new URL(frame.src);
        url.searchParams.set('_refresh', String(Date.now()));
        url.searchParams.set('_preserve_scroll', 'true');
        frame.src = url.toString();
    }

    async refreshConversationHtml(options = {}) {
        const conversationView = document.querySelector('.conversation-view');
        if (!conversationView) return;

        const wasNearBottom = this.isNearPageBottom();
        const previousScrollY = window.scrollY;
        const previousHeight = document.documentElement.scrollHeight;

        const url = new URL(window.location.href);
        url.searchParams.set('_refresh', String(Date.now()));
        const response = await fetch(url.toString(), { cache: 'no-store' });
        if (!response.ok) return;

        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const nextConversationView = doc.querySelector('.conversation-view');
        if (!nextConversationView) return;

        conversationView.replaceWith(nextConversationView);
        this.setupCodeCopyButtons();
        this.setupPagination();
        this.setupSessionShare();
        this.restoreConversationScroll({
            preserveScroll: options.preserveScroll !== false,
            wasNearBottom,
            previousScrollY,
            previousHeight,
        });
    }

    setupSessionShare() {
        if (this.shareTimer) {
            clearInterval(this.shareTimer);
            this.shareTimer = null;
        }

        const share = document.querySelector('[data-session-share]');
        if (!share?.dataset.session) return;

        this.refreshSessionShare(share);
        this.shareTimer = setInterval(() => this.refreshSessionShare(share), 30000);
    }

    async refreshSessionShare(share) {
        try {
            const response = await fetch(`/api/share-url/${encodeURIComponent(share.dataset.session)}`, {
                cache: 'no-store',
            });
            if (!response.ok) return;

            const data = await response.json();
            if (!data.url || share.href === data.url) return;

            share.href = data.url;
            share.title = `Open on LAN: ${data.url}`;
            const image = share.querySelector('img');
            if (image && data.qr_src) {
                image.src = data.qr_src;
                image.alt = `QR for ${data.url}`;
            }
            const label = share.querySelector('span');
            if (label) {
                label.textContent = data.url.replace(/^https?:\/\//, '');
            }
        } catch (error) {
            // The QR is a convenience; keep the page quiet if the refresh misses.
        }
    }

    isNearPageBottom(threshold = 120) {
        return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - threshold;
    }

    restoreConversationScroll({ preserveScroll, wasNearBottom, previousScrollY, previousHeight }) {
        if (!preserveScroll) {
            this.setupConversationScroll();
            return;
        }

        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                const scrollEl = document.scrollingElement || document.documentElement;
                const newHeight = scrollEl.scrollHeight;
                if (wasNearBottom) {
                    scrollEl.scrollTop = newHeight;
                    return;
                }
                const heightDelta = newHeight - previousHeight;
                scrollEl.scrollTop = Math.max(previousScrollY + heightDelta, 0);
            });
        });
    }

    async handleSessionSend(event, form) {
        event.preventDefault();

        const input = form.querySelector('.session-send-input');
        const button = form.querySelector('.session-send-button');
        const message = input?.value.trim();
        if (!message || form.dataset.live !== 'true') return;

        this.setSessionSendStatus(form, 'sending');
        if (button) button.disabled = true;

        try {
            const response = await fetch('/api/session-send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    project_name: form.dataset.project || '',
                    session_id: form.dataset.session || '',
                }),
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Send failed');
            }

            if (input) input.value = '';
            this.setSessionSendStatus(form, 'sent');
            window.setTimeout(() => this.refreshConversationHtml({ preserveScroll: true }), 1200);
        } catch (error) {
            this.setSessionSendStatus(form, error.message || 'failed');
        } finally {
            if (button && form.dataset.live === 'true') button.disabled = false;
        }
    }

    setSessionSendStatus(form, status) {
        const statusEl = form.querySelector('[data-session-send-status]');
        if (!statusEl) return;

        statusEl.textContent = status;
        if (status === 'sent') {
            window.setTimeout(() => {
                if (statusEl.textContent === 'sent') {
                    statusEl.textContent = '';
                }
            }, 2500);
        }
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
        this.appendLiveMessage('user', '>', prompt);
        this.ensureLiveAssistantMessage();
        this.scrollLivePanel();
    }

    appendLiveMessage(role, label, text) {
        const messages = document.getElementById('live-claude-messages');
        if (!messages) return null;

        const message = document.createElement('section');
        message.className = `terminal-turn live-message ${role}`;

        const header = document.createElement('div');
        header.className = 'terminal-prompt';

        const marker = document.createElement('span');
        marker.className = 'terminal-marker';
        marker.textContent = label;
        header.appendChild(marker);

        const content = document.createElement('pre');
        content.className = 'terminal-content live-message-content';
        content.textContent = text;

        message.append(header, content);
        messages.appendChild(message);
        this.scrollLivePanel();
        return content;
    }

    ensureLiveAssistantMessage() {
        if (this.liveAssistantContent) return;

        this.liveAssistantContent = this.appendLiveMessage('assistant', '⏺', '');
    }

    appendLiveAssistantDelta(text) {
        if (!text) return;

        this.ensureLiveAssistantMessage();
        this.liveAssistantText += text;
        this.liveAssistantContent.textContent = this.liveAssistantText;
        this.scrollLivePanel();
    }

    appendLiveSystemMessage(text) {
        this.appendLiveMessage('system', 'system', text);
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

    getSavedTheme() {
        return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light';
    }

    applyTheme(theme) {
        const isDark = theme === 'dark';
        document.body.classList.toggle('dark-theme', isDark);
        document.body.classList.toggle('light-theme', !isDark);
        document.documentElement.classList.toggle('dark-theme', isDark);
        document.documentElement.classList.toggle('light-theme', !isDark);
        localStorage.setItem('theme', theme);
        this.updateThemeToggle(theme);
        this.syncFrameTheme();
    }

    updateThemeToggle(theme) {
        const isDark = theme === 'dark';
        document.querySelectorAll('[data-theme-toggle]').forEach(toggle => {
            const icon = toggle.querySelector('[data-theme-icon]');
            const label = toggle.querySelector('[data-theme-label]');
            toggle.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
            toggle.setAttribute('title', isDark ? 'Switch to light theme' : 'Switch to dark theme');
            toggle.classList.toggle('is-dark', isDark);
            if (icon) {
                icon.className = isDark ? 'bi bi-sun' : 'bi bi-moon-stars';
            }
            if (label) {
                label.textContent = isDark ? 'Light' : 'Dark';
            }
        });
    }

    syncFrameTheme() {
        const frame = document.querySelector('iframe[name="conversation-frame"]');
        try {
            if (!frame?.contentDocument?.body) return;

            const theme = this.getSavedTheme();
            const isDark = theme === 'dark';
            frame.contentDocument.body.classList.toggle('dark-theme', isDark);
            frame.contentDocument.body.classList.toggle('light-theme', !isDark);
            frame.contentDocument.documentElement.classList.toggle('dark-theme', isDark);
            frame.contentDocument.documentElement.classList.toggle('light-theme', !isDark);
        } catch {
            // The iframe is same-origin in normal use; ignore transient access errors.
        }
    }

    toggleTheme() {
        const nextTheme = this.getSavedTheme() === 'dark' ? 'light' : 'dark';
        this.applyTheme(nextTheme);
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
