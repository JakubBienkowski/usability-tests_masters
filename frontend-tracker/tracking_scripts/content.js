function injectTrackingScript() {
    console.count('injectTrackingScript called');
    if (window._trackingScriptInjected) {
        console.warn("Tracking script already injected, skipping. _trackingScriptInjected =", window._trackingScriptInjected);
        return;
    }
    window._trackingScriptInjected = true;
    console.log("Setting _trackingScriptInjected = true");
    const script = document.createElement('script');
    script.textContent = `(${trackingCode})()`;
    document.documentElement.appendChild(script);
    script.remove();
}


const trackingCode = () => {
    return (() => {
        const backendApiUrl = 'http://localhost:8000';
        if (window._tracking_initialized) {
            return;
        }
        window._tracking_initialized = true;
        const cache = {
            interactiveElements: new Set(),
            visibilityStatus: new Map()
        };
        const originalConsoleLog = console.log;
        const originalConsoleWarn = console.warn;
        const originalConsoleError = console.error;
        const originalConsoleDebug = console.debug;

        console.log = function(...args) {
            originalConsoleLog.apply(console, ["[JS Console] LOG:", ...args]);
            originalConsoleLog.apply(console, args);
        };

        console.warn = function(...args) {
            originalConsoleWarn.apply(console, ["[JS Console] WARN:", ...args]);
            originalConsoleWarn.apply(console, args);
        };

        console.error = function(...args) {
            originalConsoleError.apply(console, ["[JS Console] ERROR:", ...args]);
            originalConsoleError.apply(console, args);
        };

        console.debug = function(...args) {
            originalConsoleDebug.apply(console, ["[JS Console] DEBUG:", ...args]);
            originalConsoleDebug.apply(console, args);
        };

        function isInteractiveCandidate(element) {
            if (cache.interactiveElements.has(element)) return true;
            if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
            const tagName = element.tagName.toLowerCase();
            const interactiveElements = new Set([
                "a", "button", "input", "select", "textarea", "details", "summary"
            ]);

            const isInteractive = interactiveElements.has(tagName) ||
                element.hasAttribute("onclick") ||
                element.hasAttribute("role") ||
                element.hasAttribute("tabindex") ||
                [...element.attributes].some(attr => attr.name.startsWith("aria-") || attr.name.startsWith("data-action"));

            if (isInteractive) cache.interactiveElements.add(element);
            return isInteractive;
        }
        function getXPath(element) {
            if (!element) return '';
            if (element.id) return `//*[@id="${element.id}"]`;
            
            const paths = [];
            while (element.nodeType === Node.ELEMENT_NODE) {
                let currentPath = element.tagName.toLowerCase();
                const sameTagSiblings = Array.from(element.parentNode.children)
                    .filter(el => el.tagName === element.tagName);
                
                if (sameTagSiblings.length > 1) {
                    const index = sameTagSiblings.indexOf(element) + 1;
                    currentPath += `[${index}]`;
                }
                
                paths.unshift(currentPath);
                element = element.parentNode;
            }
            
            return '/' + paths.join('/');
        }

        function getCssPath(element) {
            if (!element) return '';
            if (element.id) return `#${element.id}`;
            
            const path = [];
            while (element.nodeType === Node.ELEMENT_NODE) {
                let selector = element.tagName.toLowerCase();
                
                if (element.id) {
                    selector += `#${element.id}`;
                    path.unshift(selector);
                    break;
                } else {
                    if (element.className) {
                        selector += `.${Array.from(element.classList).join('.')}`;
                    }
                    
                    const sameTagSiblings = Array.from(element.parentNode.children)
                        .filter(el => el.tagName === element.tagName);
                    
                    if (sameTagSiblings.length > 1) {
                        const index = sameTagSiblings.indexOf(element) + 1;
                        selector += `:nth-child(${index})`;
                    }
                    
                    path.unshift(selector);
                }
                
                element = element.parentNode;
            }
            
            return path.join(' > ');
        }
        function quickVisibilityCheck(element) {
            if (cache.visibilityStatus.has(element)) {
                return cache.visibilityStatus.get(element);
            }

            const isVisible = element.offsetWidth > 0 &&
                element.offsetHeight > 0 &&
                !element.hasAttribute("hidden") &&
                element.style.display !== "none" &&
                element.style.visibility !== "hidden";

            cache.visibilityStatus.set(element, isVisible);
            return isVisible;
        }


        let actionQueue = [];
        let isProcessingQueue = false;
        const MAX_QUEUE_SIZE = 200;

        function processActionQueue() {
            if (isProcessingQueue || actionQueue.length === 0) return;
            isProcessingQueue = true;
            console.debug('processActionQueue - START - Queue length:', actionQueue.length);

            const actionData = actionQueue.shift();
            if (actionData) {
                console.debug('processActionQueue - Processing action type:', actionData.type);
                window.pythonProcessAction(actionData).then(() => {
                    console.debug('processActionQueue - Action type processed SUCCESSFULLY:', actionData.type);
                    isProcessingQueue = false;
                    if (actionQueue.length > 0) {
                        setTimeout(processActionQueue, 50);
                    }
                }).catch(error => {
                    console.error('processActionQueue - Error processing action type:', actionData.type, 'Error:', error);
                    isProcessingQueue = false;
                    if (actionQueue.length > 0) {
                        setTimeout(processActionQueue, 1000);
                    }
                });
            } else {
                isProcessingQueue = false;
            }
            console.debug('processActionQueue - END - Queue length:', actionQueue.length);
        }

        window._trackAction = async (type, eventData) => {
            const actionData = {
                type: type,
                event_data: eventData,
                timestamp: new Date().toISOString(),
                url: window.location.href,
                title: document.title,
                referrer: document.referrer,
            };

            actionQueue.push(actionData);

            if (actionQueue.length > MAX_QUEUE_SIZE) {
                actionQueue.shift();
                console.warn("Action queue is full, dropping oldest action.");
            }


            if (!isProcessingQueue && actionQueue.length === 1) {
                setTimeout(processActionQueue, 100);
            } else if (!isProcessingQueue && actionQueue.length > 1) {
                processActionQueue();
            }
        };


        let inputDebounceTimer = null; 
        let focusedLoginElement = null;

        document.addEventListener('focusin', (e) => {
            focusedLoginElement = e.target;
        });
        document.addEventListener('focusout', () => {
            focusedLoginElement = null;
        });

        document.addEventListener('input', (e) => {
            if (inputDebounceTimer) clearTimeout(inputDebounceTimer);

            inputDebounceTimer = setTimeout(() => {
                const eventData = {
                    element: e.target.tagName.toLowerCase(),
                    type: e.target.type,
                    id: e.target.id || '',
                    name: e.target.name || '',
                    placeholder: e.target.placeholder || '',
                    'aria-label': e.target.getAttribute('aria-label') || '',
                    valueLength: e.target.value.length,
                    value: e.target.value // Still send the value at the end of typing
                };
                window._trackAction('input', eventData); // Only track action AFTER debounce
                inputDebounceTimer = null; 
            }, 500); // 500ms debounce delay
        });
        let clickDebounceTimer = null;

        function getElementContext(element) {
            if (!element) return null;
            const getBasicElementInfo = (el) => el ? {
                tagName: el.tagName.toLowerCase(),
                className: el.className,
                id: el.id,
                textContent: el.textContent?.trim()?.substring(0, 100) // Limit text content length
            } : null;

            return {
                parent: getBasicElementInfo(element.parentElement),
                grandparent: getBasicElementInfo(element.parentElement?.parentElement),
                previousSibling: getBasicElementInfo(element.previousElementSibling),
                nextSibling: getBasicElementInfo(element.nextElementSibling)
            };
        }

        document.addEventListener('click', async (e) => {
            if (clickDebounceTimer) clearTimeout(clickDebounceTimer);

            clickDebounceTimer = setTimeout(async () => {
                const target = e.target;
                const eventData = { // Generic event data for click
                    element: target.tagName.toLowerCase(),
                    text: target.textContent?.trim() || '',
                    id: target.id || '',
                    name: target.name || '',
                    href: target.href || '',
                    'aria-label': target.getAttribute('aria-label') || '',
                    'data-testid': target.getAttribute('data-testid') || '',
                    role: target.getAttribute('role') || '',
                    x: e.pageX,
                    y: e.pageY,
                    classList: (target.classList && target.classList.length > 0) ? Array.from(target.classList) : [],
                };
                window._trackAction('click', eventData);

            }, 50);
        });


        document.addEventListener('submit', (e) => {
            console.log("--- submit event listener TRIGGERED ---");
            const form = e.target;
            const eventData = { // Generic event data for form submit
                formId: form.id || 'unnamed_form',
                action: form.action || window.location.href,
                method: form.method || 'get',
                inputs: Array.from(form.querySelectorAll('input:not([type="password"])'))
                    .map(input => ({
                        type: input.type,
                        id: input.id || '',
                        name: input.name || ''
                    })),
                passwordCount: form.querySelectorAll('input[type="password"]').length,
            };


            window._trackAction('form_submit', eventData); // Send generic 'form_submit' action
        }, { passive: true });


        let scrollTimeout;
        let lastScrollPercent = -1;
        document.addEventListener('scroll', (e) => {
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                const scrollPercent = Math.round((window.scrollY / (document.body.scrollHeight - window.innerHeight)) * 100);
                if (isNaN(scrollPercent) || Math.abs(scrollPercent - lastScrollPercent) < 5) return;

                lastScrollPercent = scrollPercent;
                const eventData = { // Generic event data for scroll
                    position: window.scrollY,
                    percent: scrollPercent
                };
                window._trackAction('scroll', eventData); // Send generic 'scroll' action
            }, 100);
        }, { passive: true });


        document.addEventListener('visibilitychange', () => {
            const eventData = { // Generic event data for visibility change
                visible: !document.hidden
            };
            window._trackAction('visibility', eventData); // Send generic 'visibility' action
        });
        const originalFetch = window.fetch;
        window.fetch = async (...args) => {
            const request = args[0] instanceof Request ? args[0] : new Request(...args);
            const response = await originalFetch(...args);
            const clonedResponse = response.clone(); // Clone for reading headers

            try {
                const headers = clonedResponse.headers;
                const contentDisposition = headers.get('Content-Disposition');
                if (contentDisposition && contentDisposition.includes('attachment')) {
                    const filenameMatch = contentDisposition.match(/filename="([^"]+)"/);
                    const filename = filenameMatch ? filenameMatch[1] : 'unknown_file';
                    const downloadDetails = {
                        url: request.url,
                        filename: filename,
                        mimeType: headers.get('Content-Type') || 'application/octet-stream',
                        status: response.status,
                        statusText: response.statusText
                    };
                    window._trackAction('download', downloadDetails); // Track 'download' action
                }
            } catch (error) {
                console.error('Error checking for download headers:', error);
            }
            return response; 
        };


        window._trackAction('pageload', { // Keep pageload action
            title: document.title,
            referrer: document.referrer,
            loadTime: performance.now()
        });


        document.addEventListener('click', (e) => {
            let button = null;
            let target = e.target;
        
            while (target && target !== document.body) {
                if (target.tagName === 'BUTTON' || 
                    target.getAttribute('role') === 'button' ||
                    target.type === 'button' ||
                    target.type === 'submit') {
                    button = target;
                    break;
                }
                target = target.parentNode;
            }
        
            if (button) {
                const eventData = {
                    element: button.tagName.toLowerCase(),
                    text: button.textContent?.trim() || button.value || '',
                    id: button.id || '',
                    name: button.name || '',
                    type: button.type || '',
                    role: button.getAttribute('role') || '',
                    'aria-label': button.getAttribute('aria-label') || '',
                    'data-testid': button.getAttribute('data-testid') || '',
                    disabled: button.disabled || false,
                    x: e.pageX,
                    y: e.pageY,
                    viewportX: e.clientX,
                    viewportY: e.clientY,
                    classList: (button.classList && button.classList.length > 0) ? Array.from(button.classList) : [],
                    attributes: Array.from(button.attributes).map(attr => ({
                        name: attr.name,
                        value: attr.value
                    })),
                    href: button.href || '',
                    xpath: getXPath(button), 
                    cssPath: getCssPath(button),
                    context: getElementContext(button)
                };
                window._trackAction('button_click', eventData);
            }
        }, true);

        
        let hoverThrottleTimer = null;
        let lastHoveredElement = null;

        function trackInteractiveElement(e) {
            if (hoverThrottleTimer) clearTimeout(hoverThrottleTimer);

            hoverThrottleTimer = setTimeout(() => {
                const target = e.target;

                if (target === lastHoveredElement) return;
                lastHoveredElement = target;

                if (isInteractiveCandidate(target) && quickVisibilityCheck(target)) {
                    const eventData = {
                        element: target.tagName.toLowerCase(),
                        id: target.id ? target.id : null,
                        text: target.textContent?.trim() || ''
                    };
                    window._trackAction('interactive_hover', eventData);
                }
            }, 300);
        }
        document.addEventListener('mouseover', trackInteractiveElement, { passive: true });


        const navigationObserver = new PerformanceObserver((list) => {
            list.getEntriesByType("navigation").forEach(entry => {
                const eventData = {
                    type: 'navigation',
                    navigation_type: 'traditional_navigation',
                    url: window.location.href,
                    startTime: entry.startTime,
                    duration: entry.duration,
                    domComplete: entry.domComplete,
                    loadEventEnd: entry.loadEventEnd,
                    context: 'traditional_navigation_performance_observer'
                };
                window._trackAction('navigation', eventData);
                console.log("Navigation Action Tracked (PerformanceObserver - Full Page Load):", eventData);
            });
        });
        navigationObserver.observe({ type: "navigation", buffered: true });

        (() => {
            const originalPushState = window.history.pushState;
            const originalReplaceState = window.history.replaceState;

            window.history.pushState = function(state, title, url) {
                const currentUrl = String(url || window.location.href);
                const navigationType = 'SPA_pushState';
                const triggerSource = 'pushState_api';

                const navigationDetails = {
                    type: 'navigation',
                    navigation_type: navigationType,
                    url: currentUrl,
                    timestamp: new Date().toISOString(),
                    context: `SPA_navigation_${triggerSource}`
                };
                window._trackAction('navigation', navigationDetails);
                console.log(`Navigation Action Tracked (pushState - SPA):`, navigationDetails);

                return originalPushState.apply(this, arguments);
            };

            window.history.replaceState = function(state, title, url) {
                const currentUrl = String(url || window.location.href);
                const navigationType = 'SPA_replaceState'; 
                const triggerSource = 'replaceState_api';

                const navigationDetails = {
                    type: 'navigation',
                    navigation_type: navigationType,
                    url: currentUrl,
                    timestamp: new Date().toISOString(),
                    context: `SPA_navigation_${triggerSource}`
                };
                window._trackAction('navigation', navigationDetails);
                console.log(`Navigation Action Tracked (replaceState - SPA):`, navigationDetails);

                return originalReplaceState.apply(this, arguments);
            };
        })();

        window.addEventListener('popstate', (event) => {
            const currentUrl = window.location.href;
            const navigationType = 'SPA_popstate';
            const triggerSource = 'popstate_event';

            const navigationDetails = {
                type: 'navigation',
                navigation_type: navigationType,
                url: currentUrl,
                timestamp: new Date().toISOString(),
                context: `SPA_navigation_${triggerSource}`
            };
            window._trackAction('navigation', navigationDetails);
            console.log(`Navigation Action Tracked (popstate - SPA Back/Forward):`, navigationDetails);
        });


        window.addEventListener('hashchange', (event) => {
            const currentUrl = window.location.href;
            const navigationType = 'SPA_hashchange'; 
            const triggerSource = 'hashchange_event';

            const navigationDetails = {
                type: 'navigation',
                navigation_type: navigationType,
                url: currentUrl,
                timestamp: new Date().toISOString(),
                context: `SPA_navigation_${triggerSource}`
            };
            window._trackAction('navigation', navigationDetails);
            console.log(`Navigation Action Tracked (hashchange - SPA Hash Navigation):`, navigationDetails);
        });

        
        window.pythonProcessAction = async (actionData) => {
            const apiUrl = backendApiUrl + '/actions/';
            try {
                const response = await fetch(apiUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(actionData)
                });
                if (!response.ok) {
                    console.error('API request failed:', response.status, response.statusText);
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                return data;
            } catch (error) {
                console.error('Error sending action to backend:', error);
                throw error;
            }
        };

        // Track copy events with content
        document.addEventListener('copy', (e) => {
            const selection = window.getSelection();
            const selectedText = selection.toString();
            const eventData = {
                type: 'copy',
                text: selectedText,
                text_length: selectedText.length,
                element: e.target.tagName.toLowerCase(),
                element_type: e.target.type || '',
                is_input: e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA',
                source_id: e.target.id || '',
                source_class: Array.from(e.target.classList || []).join(' '),
                source_url: window.location.href,
                timestamp: new Date().toISOString()
            };
            window._trackAction('copy', eventData);
        });

        // Track paste events with content
        document.addEventListener('paste', (e) => {
            const pastedText = e.clipboardData.getData('text');
            const eventData = {
                type: 'paste',
                text: pastedText,
                text_length: pastedText.length,
                element: e.target.tagName.toLowerCase(),
                element_type: e.target.type || '',
                is_input: e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA',
                target_id: e.target.id || '',
                target_class: Array.from(e.target.classList || []).join(' '),
                target_url: window.location.href,
                timestamp: new Date().toISOString()
            };
            window._trackAction('paste', eventData);
        });

        // Track cut events with content
        document.addEventListener('cut', (e) => {
            const selection = window.getSelection();
            const selectedText = selection.toString();
            const eventData = {
                type: 'cut',
                text: selectedText,
                text_length: selectedText.length,
                element: e.target.tagName.toLowerCase(),
                element_type: e.target.type || '',
                is_input: e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA',
                source_id: e.target.id || '',
                source_class: Array.from(e.target.classList || []).join(' '),
                source_url: window.location.href,
                timestamp: new Date().toISOString()
            };
            window._trackAction('cut', eventData);
        });

    })();
};

injectTrackingScript();
console.log("Tracking script injected.");