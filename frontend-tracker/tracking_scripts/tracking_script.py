tracking_js_code = r"""
                () => {
                    // Only initialize if not already initialized
                   
                    if (window._tracking_initialized) {
                        return;
                    }
                    window._tracking_initialized = true;
                    function isLoginPageUrl() {
                        return false; // Replace with actual logic later if needed
                    }

                    // Placeholder function for isLoginForm - always returns false for now
                    function isLoginForm(form) {
                        if (!form || form.nodeName !== 'FORM') {
                            return false;
                        }
                        console.debug("isLoginForm: Checking form:", form); // Log the form element itself

                        // 1. Check for password input field
                        if (form.querySelector('input[type="password"]')) {
                            console.debug("isLoginForm: Found password input - returning true (heuristic 1)");
                            return true;
                        }
                        console.debug("isLoginForm: No password input field found (heuristic 1 failed)");

                        // 2. Check form action URL keywords
                        const formAction = (form.action || '').toLowerCase();
                        console.debug(`isLoginForm: Form action: ${formAction}`); // Log formAction
                        if (formAction.includes('/login') || formAction.includes('/signin') || formAction.includes('/auth')) {
                            console.debug("isLoginForm: Form action keywords match - returning true (heuristic 2)");
                            return true;
                        }
                        console.debug("isLoginForm: Form action keywords not found (heuristic 2 failed)");

                        // 3. Check form ID or Name keywords
                        const formId = (form.id || '').toLowerCase();
                        const formName = (form.name || '').toLowerCase();
                        console.debug(`isLoginForm: Form ID: ${formId}, Form Name: ${formName}`); // Log formId and formName
                        if (formId.includes('login') || formId.includes('signin') || formName.includes('login') || formName.includes('signin')) {
                            console.debug("isLoginForm: Form ID/Name keywords match - returning true (heuristic 3)");
                            return true;
                        }
                        console.debug("isLoginForm: Form ID/Name keywords not found (heuristic 3 failed)");

                        // 4. Check for input fields with names/IDs related to username/email and password
                        const inputs = Array.from(form.elements);
                        const hasPasswordInput = inputs.some(el => (el.name || '').toLowerCase().includes('password') || (el.id || '').toLowerCase().includes('password'));
                        const hasUsernameEmailInput = inputs.some(el => (el.name || '').toLowerCase().includes('username') || (el.name || '').toLowerCase().includes('email') || (el.id || '').toLowerCase().includes('username') || (el.id || '').toLowerCase().includes('email'));

                        console.debug(`isLoginForm: Checking for username/email and password input pairs - Password Input: ${hasPasswordInput}, Username/Email Input: ${hasUsernameEmailInput}`); // Log input checks
                        if (hasPasswordInput && hasUsernameEmailInput) {
                            console.debug("isLoginForm: Username/email and password input pair found - returning true (heuristic 4)");
                            return true;
                        }
                        console.debug("isLoginForm: Username/email and password input pair not found (heuristic 4 failed)");

                        console.debug("isLoginForm: No login form heuristics matched - returning false");
                        return false; // If none of the heuristics match, consider it NOT a login form
                    }
                    // Your existing tracking code here...
                    // Cache common DOM queries to improve performance
                    const cache = {
                        interactiveElements: new Set(),
                        visibilityStatus: new Map()
                    };
                                    const originalConsoleLog = console.log;
                    const originalConsoleWarn = console.warn;
                    const originalConsoleError = console.error;
                    const originalConsoleDebug = console.debug;

                    console.log = function(...args) {
                        window.pythonLogger('log', ...args); // Call Python logger for 'log'
                        originalConsoleLog.apply(console, args); // Still log to browser console
                    };

                    console.warn = function(...args) {
                        window.pythonLogger('warn', ...args); // Call Python logger for 'warn'
                        originalConsoleWarn.apply(console, args); // Still log to browser console
                    };

                    console.error = function(...args) {
                        window.pythonLogger('error', ...args); // Still log to browser console
                        originalConsoleError.apply(console, args); // Still log to browser console
                    };

                    console.debug = function(...args) {
                        window.pythonLogger('debug', ...args); // Call Python logger for 'debug'
                        originalConsoleDebug.apply(console, args); // Still log to browser console
                    };
                    const logoutRequestKeywords = ['/logout', '/signout', '/exit', '/deauth', '/invalidate-session']; // Expanded keywords for logout
                    const logoutPageKeywords = ['/logout', '/signout', '/exit'];
                    function isLogoutUrl(url) {
                        if (!url) return false;
                        const lowerUrl = url.toLowerCase();
                        return logoutRequestKeywords.some(keyword => lowerUrl.includes(keyword));
                    }

                    // ----- Enhanced DOM helper functions from dom/buildDomTree.js -----
                    function isInteractiveCandidate(element) {
                        // Performance optimization: Check cache first
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

                        // Cache the result for subsequent checks
                        if (isInteractive) cache.interactiveElements.add(element);
                        return isInteractive;
                    }

                    function quickVisibilityCheck(element) {
                        // Performance optimization: Check cache first
                        if (cache.visibilityStatus.has(element)) {
                            return cache.visibilityStatus.get(element);
                        }

                        const isVisible = element.offsetWidth > 0 &&
                            element.offsetHeight > 0 &&
                            !element.hasAttribute("hidden") &&
                            element.style.display !== "none" &&
                            element.style.visibility !== "hidden";

                        // Cache the result
                        cache.visibilityStatus.set(element, isVisible);
                        return isVisible;
                    }
                    // -------------------------------------------------------------------

                    // Enhanced login detection logic
                    window._loginState = {
                        attempts: 0,
                        lastAttemptTime: null,
                        currentSession: {
                            isLoggedIn: false,
                            username: null,
                            loginTime: null
                        }
                    };

                    // Stricter Login state detection function - for logout fix

                    async function checkLoginState(recentActionsSummary) { // <-- ADD recentActionsSummary parameter
                        console.debug('--- checkLoginState() START --- (OpenAI Primary Check, with Action Context)'); // Debugging start - OpenAI Primary + Context

                        let isLoggedIn = false; // Initialize as not logged in
                        let heuristicsPassedCount = 0; // Track heuristics - for logging

                        try {
                            // --- Heuristic Checks (still run for logging/info, but not primary) ---
                            // --- Heuristic 1: Cookie check ---
                            const sessionCookieRegex = /session|auth|token|sid|user|jwt|csrf/i;
                            const cookies = document.cookie.split(';');
                            const hasSessionLikeCookie = cookies.some(cookie => {
                                const cookieTrimmedLower = cookie.trim().toLowerCase();
                                const cookieName = cookieTrimmedLower.split('=')[0];
                                const isMatch = sessionCookieRegex.test(cookieName);
                                console.log(`Cookie check: '${cookie.trim()}', Match: ${isMatch}`);
                                return isMatch;
                            });
                            if (hasSessionLikeCookie) heuristicsPassedCount++;

                            // --- Heuristic 2: Storage check ---
                            const sessionStorageRegex = /session|auth|token|user|jwt|csrf/i;
                            const hasSessionLikeStorage = [...Object.keys(localStorage), ...Object.keys(sessionStorage)].some(key => sessionStorageRegex.test(key.toLowerCase()));
                            if (hasSessionLikeStorage) heuristicsPassedCount++;

                            // --- Strong check for 'token' cookie specifically ---
                            const hasTokenCookie = cookies.some(cookie => {
                                const trimmedCookie = cookie.trim();
                                console.log(`Checking cookie for token: ${trimmedCookie}`);
                                return trimmedCookie.startsWith('token=');
                            });
                            if (hasTokenCookie) heuristicsPassedCount++;

                            // --- Heuristic 3: DOM indicators ---
                            const domLoginIndicators = [
                                '.user-menu', '.profile-dropdown', '.account-settings',
                                '#logout-button', 'a[href*="/logout"]',
                                '.dashboard-link', 'a[href*="/dashboard"]', '#account-page-link',
                                'a[href*="/account"]', '[aria-label="User Profile"]',
                                '[role="menu"] [aria-label*="account"]'
                            ];
                            const hasDomLoginIndicator = domLoginIndicators.some(selector => {
                                try {
                                    return document.querySelector(selector) !== null;
                                } catch (e) {
                                    console.log(`Error checking selector ${selector}: ${e}`);
                                    return false;
                                }
                            });
                            if (hasDomLoginIndicator) heuristicsPassedCount++;

                            // --- Heuristic 4: Login form absence ---
                            const loginFormSelectors = [
                                'form[action*="/login"]',
                                'form[action*="/signin"]',
                                '#login-form',
                                '.login-form',
                                'form:has(input[type="password"])'
                            ].join(',');
                            const isLoginFormPresent = document.querySelector(loginFormSelectors) !== null;
                            if (!isLoginFormPresent) heuristicsPassedCount++;

                            console.debug(`checkLoginState - Heuristic Check (for info): ${heuristicsPassedCount} heuristics passed`); // Log heuristics count
                            isLoggedIn = heuristicsPassedCount >= 2; 
                            if (isLoggedIn) {
                                return isLoggedIn; // Skip OpenAI check if heuristics already passed
                            }
                            // --- PRIMARY LOGIN CHECK: OpenAI API Call with Action Context ---
                            if (window._use_openai_login_check) {
                                console.debug('checkLoginState - Calling OpenAI for login status WITH ACTION CONTEXT...'); // Debug log - with context
                                const htmlContent = await window.getPageContentForOpenAI(); // Get page HTML from Python

                                // Construct fullPrompt using Javascript array join()
                                const promptLines = [
                                    "Recent Browser Actions:",
                                    "```",
                                    recentActionsSummary,
                                    "```",
                                    "", // Add an empty line
                                    "HTML Content of the webpage:",
                                    "```html",
                                    htmlContent,
                                    "```",
                                    "", // Add an empty line
                                    "Analyze the recent browser actions and the HTML content of the webpage. Determine if these actions and the HTML together indicate that a user is likely logged in to a website.",
                                    "", // Add an empty line
                                    "Consider actions like form submissions (especially to login/auth URLs), button clicks (on login/sign-in buttons), and navigation events. Also, analyze the HTML for login indicators (user menus, logout links, etc.) and absence of login forms.",
                                    "", // Add an empty line
                                    "Based on this combined information, is the user likely logged in? Respond with 'yes' or 'no' only."
                                ];
                                const fullPrompt = promptLines.join('\n'); // Join array elements with newline

                                isLoggedIn = await window.pythonCheckLoginStatusWithOpenAI(fullPrompt); // Call Python/OpenAI check with FULL PROMPT
                                console.debug(`checkLoginState - OpenAI Login Check Result (with Context): ${isLoggedIn}`); // Debug log - with context
                            } else {
                                console.debug('checkLoginState - OpenAI check SKIPPED (window._use_openai_login_check is false)');
                                isLoggedIn = heuristicsPassedCount >= 2; // Fallback to heuristics
                            }

                            console.debug(`checkLoginState - Final Login Status (OpenAI Primary with Context): ${isLoggedIn}`); // Log final status - with context
                            console.debug('--- checkLoginState() END ---'); // Debugging end
                            return isLoggedIn;

                        } catch (error) {
                            console.log('Error in checkLoginState:', error);
                            return false;
                        }
                    }


                    // --- Network Request Monitoring for Login Detection ---
                    const loginRequestKeywords = ['/login', '/auth', '/signin', '/session', '/authenticate'];
                    const loginPageKeywords = ['/login', '/signin', '/auth']; // Keywords for login page URLs
                    const excludeUrls = ['/telemetry', '/metrics', '/events', '/api/status']; // Exclude telemetry URLs
                    


                    // Function to handle login attempt tracking based on request details
                    function trackLoginAttempt(url, method, requestBody) {
                        window._loginState.attempts++;
                        window._loginState.lastAttemptTime = Date.now();
                        console.log('Login Attempt Detected (Network):', method, url); // Enhanced logging
                        window._trackAction('login_attempt_network', { // New action type for network login attempts
                            url: url,
                            method: method,
                            requestBody: requestBody, // Optionally track request body (be mindful of sensitive data)
                            attemptNumber: window._loginState.attempts,
                            timestamp: new Date().toISOString()
                        });
                    }
                    function trackLogoutAttempt(url, method, requestBody) {
                        console.log('Logout Attempt Detected (Network):', method, url);
                        window._trackAction('logout_attempt_network', { //  New action type for logout attempts
                            url: url,
                            method: method,
                            requestBody: requestBody,
                            timestamp: new Date().toISOString()
                        });
                    }                    
                    async function handleLogoutResponse(url, status) {
                                    const wasSuccessful = status >= 200 && status < 300;
                                    console.log('Logout Response Received (Network):', url, status, wasSuccessful ? 'Success' : 'Failure');
                                    if (wasSuccessful) {
                                        // Logout success detected via network response
                                        if (window._loginState.currentSession.isLoggedIn) { // Double check if we were logged in before
                                            window._trackAction('logout_network', { // New action type for network logout success
                                                timestamp: new Date().toISOString(),
                                                url: url,
                                                status: status
                                            });
                                            window._loginState.currentSession.isLoggedIn = false; // Update login state
                                            console.log('Logout Detected (Network Response Success)');
                                        } else {
                                            console.warn('Logout response success, but login state was already false. Investigate.');
                                        }
                                    } else {
                                        window._trackAction('logout_failure_network', { // New action type for network logout failure
                                            timestamp: new Date().toISOString(),
                                            url: url,
                                            status: status
                                        });
                                    }
                                }

                    // Function to handle login success/failure based on response
                    async function handleLoginResponse(url, status) {
                        const wasSuccessful = status >= 200 && status < 300;
                        console.debug('handleLoginResponse - URL:', url, 'Status:', status);
                        console.log('Login Response Received (Network):', url, status, wasSuccessful ? 'Success' : 'Failure'); // Enhanced logging
                        if (wasSuccessful && !window._loginState.currentSession.isLoggedIn) {
                            // Login success detected via network response
                            window._loginState.currentSession.isLoggedIn = true;
                            window._loginState.currentSession.loginTime = new Date().toISOString();
                            window._trackAction('login_success_network', { // New action type for network login success
                                timestamp: new Date().toISOString(),
                                attempts: window._loginState.attempts,
                                loginTime: window._loginState.currentSession.loginTime,
                                url: url,
                                status: status
                            });
                        } else if (!wasSuccessful) {
                            window._trackAction('login_failure_network', { // New action type for network login failure
                                timestamp: new Date().toISOString(),
                                attemptNumber: window._loginState.attempts,
                                url: url,
                                status: status
                            });
                        }
                    }



                    // --- XMLHttpRequest Interception ---
                    const originalXHR = window.XMLHttpRequest;
                    window.XMLHttpRequest = function () {
                        const xhr = new originalXHR();
                        const originalOpen = xhr.open;
                        const originalSend = xhr.send;
                        let currentUrl, currentMethod, requestBody;

                        xhr.open = function(method, url) {
                        console.log('XHR open:', method, url); 
                            currentUrl = url;
                            currentMethod = method;
                            originalOpen.apply(xhr, arguments);
                        };

                        xhr.send = function(body) {
                            console.log('XHR send:', currentMethod, currentUrl);
                            requestBody = body ? String(body) : null; // Capture request body
                            if (isLoginUrl(currentUrl) && currentMethod.toUpperCase() === 'POST') {
                                trackLoginAttempt(currentUrl, currentMethod, requestBody);
                            }
                            if (isLogoutUrl(currentUrl) && currentMethod.toUpperCase() === 'POST') { // Check for logout URL
                                trackLogoutAttempt(currentUrl, currentMethod, requestBody); // Call new trackLogoutAttempt function
                            }
                            originalSend.apply(xhr, arguments);
                        };

                        xhr.addEventListener('load', function() {
                            console.log('XHR load - status:', xhr.status, 'URL:', currentUrl);
                            if (isLoginUrl(currentUrl) && currentMethod.toUpperCase() === 'POST') {
                                handleLoginResponse(currentUrl, xhr.status);
                            }
                            if (isLogoutUrl(currentUrl) && currentMethod.toUpperCase() === 'POST') { // Check for logout URL
                                handleLogoutResponse(currentUrl, xhr.status); // Call new handleLogoutResponse function
                            }
                        });
                        return xhr;
                    };

                    // Enhanced form submission tracking
                    document.addEventListener('submit', async (e) => {
                        console.log('submit event handler START');
                        const form = e.target;
                        const state = window._loginState;
                        const formAction = form.action || window.location.href;

                        // --- Enhanced Logout Form Detection ---
                        const isLogoutForm = formAction.toLowerCase().includes('/logout');

                        if (isLogoutForm) {
                            console.log('Logout Form Submit Detected:', form.action);
                            window._trackAction('logout_form_submit', {
                                formId: form.id || 'unnamed_form',
                                action: form.action,
                                method: form.method,
                                timestamp: new Date().toISOString()
                            });

                            // --- Call checkAuthStateChange() IMMEDIATELY for Logout Forms ---
                            console.log('Calling checkAuthStateChange() DIRECTLY after logout form submit (to trigger logout check)'); // <-- ADDED LOG
                            checkAuthStateChange(); // <--- CALL checkAuthStateChange() here
                            // --- END Call checkAuthStateChange() ---


                            console.log('Calling checkLoginState() DIRECTLY after logout form submit'); // Keep this for now, but checkAuthStateChange should be the primary trigger
                            // const stillLoggedIn = await checkLoginState();
                            console.log('checkLoginState() DIRECT CALL Result (Logout Form Submit):', stillLoggedIn);

                            if (!stillLoggedIn) {
                                window._trackAction('logout', {
                                    timestamp: new Date().toISOString(),
                                    sessionDuration: Date.now() - new Date(state.currentSession.loginTime).getTime()
                                });
                                state.currentSession.isLoggedIn = false;
                                console.log('Logout Detected (Form Submit - Logout Form)');
                            } else {
                                console.warn('Logout form submitted, but checkLoginState still says logged in. Investigate!');
                            }
                            console.log('submit event handler END (Logout Form)');
                            return;
                        }

                        // Detect if this is a login form

                        const isLoginFormResult = isLoginForm(form); // <-- Capture the result
                        console.log('DEBUG: isLoginForm(form) result:', isLoginFormResult);
                        if (isLoginFormResult) {
                            state.attempts++;
                            state.lastAttemptTime = Date.now();
                            console.log('Login Attempt Detected (Form Submit):', form.id || 'unnamed_form'); // Enhanced logging

                            // Track the form submission
                            window._trackAction('login_attempt', {
                                formId: form.id || 'unnamed_form',
                                attemptNumber: state.attempts,
                                timestamp: new Date().toISOString()
                            });

                            // Set up post-submission check
                            console.log('submit event handler END');

                            try {
                                console.log('Calling checkLoginState() DIRECTLY after submit');
                                
                                // Remove the nested Promise and simplify the flow
                                let wasSuccessful = await checkLoginState();
                                
                                // IMPORTANT: Add this log immediately after getting the result
                                console.log('checkLoginState() DIRECT CALL Result:', wasSuccessful);
                                
                                // Rest of your logic remains the same...
                                if (!wasSuccessful && window._use_openai_login_check) {
                                    // OpenAI fallback...
                                    console.log('Heuristic check failed, falling back to OpenAI login check...');
                                    const htmlContent = await window.getPageContentForOpenAI();
                                    wasSuccessful = await window.pythonCheckLoginStatusWithOpenAI(htmlContent);
                                    
                                    // IMPORTANT: Add another log here after the OpenAI check
                                    console.log(`OpenAI Login Check Result (after fallback): ${wasSuccessful}`);
                                }

                                if (!wasSuccessful && window._use_openai_login_check) { // Fallback to OpenAI if heuristic fails and OpenAI check is enabled
                                    console.log('Heuristic check failed, falling back to OpenAI login check...');
                                    const htmlContent = await window.getPageContentForOpenAI(); // Get page HTML from Python
                                    wasSuccessful = await window.pythonCheckLoginStatusWithOpenAI(htmlContent); // Call Python/OpenAI check
                                    console.log(`OpenAI Login Check Result: ${wasSuccessful}`);
                                }


                                if (wasSuccessful && !state.currentSession.isLoggedIn) {
                                    // Login success detected (either by heuristic or OpenAI)
                                    state.currentSession.isLoggedIn = true;
                                    state.currentSession.loginTime = new Date().toISOString();

                                    // Try to get username if available
                                    const possibleUserElements = document.querySelectorAll(
                                        '[class*="user"], [class*="account"], [class*="profile"]'
                                    );
                                    for (const el of possibleUserElements) {
                                        const text = el.textContent.trim();
                                        if (text && !state.failureIndicators.has(text.toLowerCase())) {
                                            state.currentSession.username = text;
                                            break;
                                        }
                                    }
                                    console.log('Login Success Detected (Form Submit Check):', state.currentSession.username || 'No Username Found');
                                    console.log('DEBUG: About to track login_success action');

                                    
                                    window._trackAction('login_success', {
                                    timestamp: new Date().toISOString(),
                                    attempts: state.attempts,
                                    username: state.currentSession.username,
                                    loginTime: state.currentSession.loginTime
                                });
                                    
                                } else if (!wasSuccessful) {
                                    const errorMessages = Array.from(document.querySelectorAll(
                                        '.error, .alert, .notification, [role="alert"], .error-message, .login-error, .auth-error' // More error selectors
                                    )).map(el => el.textContent.trim()).filter(Boolean);
                                    console.log('Login Failure Detected (Form Submit Check):', errorMessages.join('; ') || 'No Error Message'); // Enhanced logging

                                    if (errorMessages.length > 0) { // Only track as failure if error messages are found
                                        window._trackAction('login_failure', { // Track login failure with error messages
                                            timestamp: new Date().toISOString(),
                                            attemptNumber: state.attempts,
                                            errorMessages: errorMessages
                                        });
                                    } else {
                                        console.debug('Login NOT Successful (Form Submit Check) - but no error messages found, might be other issue.');
                                        // Optionally, you could track this as a 'login_not_successful' action if needed for further analysis
                                    }
                                }
                                } catch (error) {
                                    console.error('Error checking login state:', error);
                                }
                        }
                    });

                    // Monitor URL changes for login state changes
                    
                    new MutationObserver(async () => {
                        let lastUrl = location.href;
                        if (location.href !== lastUrl) {
                            console.debug('URL changed from', lastUrl, 'to', location.href); // Log URL changes
                            const wasLoggedInBeforeNav = window._loginState.currentSession.isLoggedIn; // Store login state before URL change
                            

                            if (wasLoggedInBeforeNav) { // ONLY check for logout if was previously logged in
                                console.debug('Calling checkLoginState() - URL Change (Logout Check)'); // <--- ADD THIS LOG
                                const stillLoggedIn = await checkLoginState();
                                if (!stillLoggedIn && window._use_openai_login_check) { // Fallback to OpenAI if heuristic fails and OpenAI check is enabled
                                        console.debug('Heuristic check failed (URL change), falling back to OpenAI login check...');
                                        const htmlContent = await window.getPageContentForOpenAI(); // Get page HTML from Python
                                        stillLoggedIn = await window.pythonCheckLoginStatusWithOpenAI(htmlContent); // Call Python/OpenAI check
                                        console.debug(`OpenAI Login Check Result (URL change): ${stillLoggedIn}`);
                                    }
                                console.debug('Still logged in check:', stillLoggedIn); // Log stillLoggedIn result
                                if (!stillLoggedIn) {
                                        // Logout detected via URL change
                                        window._trackAction('logout', {
                                            timestamp: new Date().toISOString(),
                                            sessionDuration: Date.now() - new Date(window._loginState.currentSession.loginTime).getTime()
                                        });
                                        window._loginState.currentSession.isLoggedIn = false;
                                        console.log('Logout Detected (URL Change) - Was logged in before nav.');
                                    } else {
                                        console.log('Still Logged In (URL Change) - Was logged in before nav.');
                                    }
                            } else {
                                console.debug('Calling checkLoginState() - URL Change (Login Detect)'); // <--- ADD THIS LOG
                                const nowLoggedIn = await checkLoginState();
                                if (!nowLoggedIn && window._use_openai_login_check) { // Fallback to OpenAI if heuristic fails and OpenAI check is enabled
                                        console.debug('Heuristic check failed (new URL), falling back to OpenAI login check...');
                                        const htmlContent = await window.getPageContentForOpenAI(); // Get page HTML from Python
                                        nowLoggedIn = await window.pythonCheckLoginStatusWithOpenAI(htmlContent); // Call Python/OpenAI check
                                        console.debug(`OpenAI Login Check Result (new URL): ${nowLoggedIn}`);
                                    }
                                console.debug('Now logged in check:', nowLoggedIn); // Log nowLoggedIn result
                                if (nowLoggedIn) {
                                    window._loginState.currentSession.isLoggedIn = true;
                                    window._loginState.currentSession.loginTime = new Date().toISOString();
                                    window._trackAction('login_detected', {
                                        timestamp: new Date().toISOString(),
                                        url: location.href
                                    });
                                    console.log('Login Detected (URL Change) - Was NOT logged in before nav.'); // Log login detected with context
                                } else {
                                    console.log('No Login Change (URL Change) - Was NOT logged in before nav.'); // Log no login change with context
                                }
                            }
                            lastUrl = location.href;
                        }
                    }).observe(document, {subtree: true, childList: true});



                    // Existing escape key and user action tracking - no changes
                    document.addEventListener('keydown', (e) => {
                        if (e.key === 'Escape') {
                            window._escapePressed = true;
                            window._trackAction('keyboard', {
                                key: 'Escape',
                                type: 'exit'
                            });
                        }
                    });

                    
                    let actionQueue = []; // Action queue in Javascript
                    let isProcessingQueue = false;

                    // Process action queue with throttling
                    function processActionQueue() {
                        if (isProcessingQueue || actionQueue.length === 0) return;
                        isProcessingQueue = true;
                        console.debug('processActionQueue - START - Queue length:', actionQueue.length); // START LOG

                        const actionData = actionQueue.shift(); // Get first action from queue
                        if (actionData) {
                            console.debug('processActionQueue - Processing action type:', actionData.type); // LOG ACTION TYPE - BEFORE SEND
                            window.pythonProcessAction(actionData).then(() => { // Process action and THEN...
                                console.debug('processActionQueue - Action type processed SUCCESSFULLY:', actionData.type); // LOG ACTION TYPE - SUCCESS
                                isProcessingQueue = false;
                                if (actionQueue.length > 0) { // If more actions in queue, process next after a short delay
                                    setTimeout(processActionQueue, 50); // Small delay before processing next action
                                }
                            }).catch(error => {
                                console.error('processActionQueue - Error processing action type:', actionData.type, 'Error:', error); // LOG ACTION TYPE - ERROR
                                isProcessingQueue = false; // Still allow queue to be processed later
                                if (actionQueue.length > 0) {
                                    setTimeout(processActionQueue, 1000); // Longer delay on error
                                }
                            });
                        } else {
                            isProcessingQueue = false; // Queue empty
                        }
                        console.debug('processActionQueue - END - Queue length:', actionQueue.length); // END LOG
                    }

                    window._trackAction = async (type, details) => {
                        const actionData = {
                            type: type,
                            details: details,
                            timestamp: new Date().toISOString(),
                            url: window.location.href,
                            title: document.title,
                            referrer: document.referrer,
                        };

                        actionQueue.push(actionData); // Add action to queue

                        if (!isProcessingQueue) { // Start queue processing if not already running
                            processActionQueue();
                        }
                    };
                    // --- Contextual Input Tracking for Login Fields - no changes
                    let inputThrottleTimer = null;
                    let focusedLoginElement = null; // Track focused login element

                    document.addEventListener('focusin', (e) => {
                        // Check if focused element is within a login context (login page or identified login form)
                        if (isLoginPageUrl() || (e.target.form && isLoginForm(e.target.form))) {
                            focusedLoginElement = e.target;
                        } else {
                            focusedLoginElement = null; // Reset if focus moves out of login context
                        }
                    });
                    document.addEventListener('focusout', () => {
                        focusedLoginElement = null; // Clear focused element on blur
                    });


                    document.addEventListener('input', (e) => {
                        if (focusedLoginElement) { // Only track input if it's in a login context
                            // Throttle input events to avoid too many events
                            if (inputThrottleTimer) clearTimeout(inputThrottleTimer);

                            inputThrottleTimer = setTimeout(() => {
                                if (e.target.type !== 'password') {
                                    let valueHint = '';
                                    if (e.target.value && e.target.value.length > 0) {
                                        valueHint = `${e.target.value.length} chars`;
                                        if (/^[0-9]+$/.test(e.target.value)) {
                                            valueHint += ' (numeric)';
                                        } else if (/[a-zA-Z]+$/.test(e.target.value)) {
                                            valueHint += ' (alphabetic)';
                                        } else if (e.target.value.includes('@')) {
                                            valueHint += ' (possible email)';
                                        }
                                    }

                                    window._trackAction('input', {
                                        element: e.target.tagName.toLowerCase(),
                                        type: e.target.type,
                                        id: e.target.id || '',
                                        name: e.target.name || '',
                                        placeholder: e.target.placeholder || '',
                                        'aria-label': e.target.getAttribute('aria-label') || '',
                                        valueHint: valueHint
                                    });
                                } else {
                                    window._trackAction('input', {
                                        element: e.target.tagName.toLowerCase(),
                                        type: 'password',
                                        id: e.target.id || '',
                                        secure: true,
                                        valueHint: 'password entered'
                                    });
                                }
                            }, 200); // Throttle to 200ms
                        }
                    });

                    // Track input changes with debouncing and completion detection - no changes
                    let inputBuffer = new Map();  // Store incomplete input changes
                    let inputTimeout = null;
                    const INPUT_COMPLETE_DELAY = 1000;  // Wait 1 second of no changes before considering complete

                    document.addEventListener('input', (e) => {
                        if (inputTimeout) clearTimeout(inputTimeout);

                        const inputKey = `${e.target.tagName}-${e.target.id || e.target.name || 'unnamed'}`;
                        const currentTime = Date.now();

                        // Update or create input buffer entry
                        inputBuffer.set(inputKey, {
                            element: e.target,
                            type: e.target.type,
                            id: e.target.id || '',
                            name: e.target.name || '',
                            placeholder: e.target.placeholder || '',
                            'aria-label': e.target.getAttribute('aria-label') || '',
                            lastChanged: currentTime,
                            isPassword: e.target.type === 'password'
                        });

                        // Set timeout to process completed inputs
                        inputTimeout = setTimeout(() => processCompletedInputs(), INPUT_COMPLETE_DELAY);
                    });

                    // Track input completion events - no changes
                    document.addEventListener('blur', (e) => {
                        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                            processInputCompletion(e.target);
                        }
                    }, true);

                    document.addEventListener('change', (e) => {
                        if (e.target.tagName === 'SELECT') {
                            processInputCompletion(e.target);
                        }
                    }, true);

                    // Process completed inputs - no changes
                    function processCompletedInputs() {
                        const currentTime = Date.now();

                        for (const [key, data] of inputBuffer.entries()) {
                            if (currentTime - data.lastChanged >= INPUT_COMPLETE_DELAY) {
                                processInputCompletion(data.element);
                                inputBuffer.delete(key);
                            }
                        }
                    }

                    // Process a single completed input - no changes
                    function processInputCompletion(element) { // 'element' is already passed as argument
                        let valueHint = '';

                        if (element.type === 'password') {
                            valueHint = 'password entered (value hidden)';
                        } else if (element.value && element.value.length > 0) {
                            valueHint = `${element.value.length} chars`;
                            if (/^[0-9]+$/.test(element.value)) {
                                valueHint += ' (numeric)';
                            } else if (/[a-zA-Z]+$/.test(element.value)) {
                                valueHint += ' (alphabetic)';
                            } else if (element.value.includes('@')) {
                                valueHint += ' (possible email)';
                            }
                        }

                        window._trackAction('input_complete', {
                            element: element.tagName.toLowerCase(),
                            type: element.type,
                            id: element.id || '',
                            name: element.name || '',
                            placeholder: element.placeholder || '',
                            'aria-label': element.getAttribute('aria-label') || '', // Use 'element', not 'e.target'
                            valueHint: valueHint,
                            secure: element.type === 'password'
                        });
                    }

                    
                    let clickDebounceTimer = null;
                    document.addEventListener('click', async (e) => {
                        if (clickDebounceTimer) clearTimeout(clickDebounceTimer);

                        clickDebounceTimer = setTimeout(async () => {
                            const text = e.target.textContent?.trim() || '';
                            const tagName = e.target.tagName.toLowerCase();
                            const id = e.target.id || '';
                            const name = e.target.name || '';
                            const href = e.target.href || '';
                            if (text === 'Sign Out' || text === 'Sign out' || text === 'Log Out' || text === 'Log out' ||
                                (tagName === 'a' && href.toLowerCase().includes('/logout')) ||
                                e.target.closest('#logout-menu-item, .logout-button, [data-testid="logout"]')) {
                                console.log('DEBUG: Sign Out Click Detected!');
                                await window._trackAction('logout_initiated', { 
                                    type: 'menu_click',
                                    element: tagName,
                                    text: text,
                                    href: href,
                                    id: id,
                                    name: name
                                });
                                return; // Exit early for logout actions
                            }

                            const aria = e.target.getAttribute('aria-label') || '';
                            const dataTestId = e.target.getAttribute('data-testid') || '';
                            const role = e.target.getAttribute('role') || '';
                            const elementContext = await getSurroundingContext(e.target, 3);
                            const textualContext = getTextualContext(e.target);
                            // Optimize path collection - only collect first 3 levels
                            const path = [];
                            let node = e.target;
                            let i = 0;
                            while (node && node !== document && i < 3) {
                                path.push({
                                    tag: node.tagName.toLowerCase(),
                                    id: node.id || null,
                                    classes: node.classList.length > 0 ? Array.from(node.classList).join(' ') : null
                                });
                                node = node.parentNode;
                            }

                            const clickDetails = { // Create an object to log
                                element: tagName,
                                text: text,
                                id: id,
                                name: name,
                                href: href,
                                'aria-label': aria,
                                'data-testid': dataTestId,
                                role: role,
                                path: path,
                                x: e.pageX,
                                y: e.pageY,
                                classList: (e.target.classList && e.target.classList.length > 0) ? Array.from(e.target.classList) : [],
                                elementContext: elementContext,
                                textualContext: textualContext
                            };
                            console.log("DEBUG: Javascript Click Details before sending to Python:", clickDetails);
                            window.pythonLogger('log', "DEBUG: pythonLogger TEST MESSAGE FROM CLICK HANDLER"); // ADD THIS TEST CALL
                            window._trackAction('click', clickDetails);

                            window._trackAction('click', clickDetails); // Use the clickDetails object

                        }, 50);
                    });

                    // Enhanced form tracking with special login detection - no changes
                    document.addEventListener('submit', (e) => {
                        const formId = e.target.id || 'unnamed_form';
                        const formAction = e.target.action || window.location.href;
                        const formMethod = e.target.method || 'get';
                        const inputs = Array.from(e.target.querySelectorAll('input:not([type="password"])'))
                            .map(input => ({
                                type: input.type,
                                id: input.id || '',
                                name: input.name || ''
                            }));
                        const passwordCount = e.target.querySelectorAll('input[type="password"]').length;

                        // Determine if this is likely a login form
                        const possibleLogin = passwordCount > 0 ||
                            (formAction.toLowerCase().includes('login')) ||
                            (formAction.toLowerCase().includes('signin')) ||
                            (formId.toLowerCase().includes('login')) ||
                            (formId.toLowerCase().includes('signin')) ||
                            Array.from(e.target.elements).some(el =>
                                (el.id && (el.id.toLowerCase().includes('login') || el.id.toLowerCase().includes('username') ||
                                        el.id.toLowerCase().includes('email'))) ||
                                (el.name && (el.name.toLowerCase().includes('login') || el.name.toLowerCase().includes('username') ||
                                            el.name.toLowerCase().includes('email')))
                            );

                        // Track the form submission
                        window._trackAction('form_submit', {
                            formId: formId,
                            action: formAction,
                            method: formMethod,
                            inputs: inputs,
                            passwordCount: passwordCount,
                            hasPassword: passwordCount > 0,
                            possibleLogin: possibleLogin
                        });

                        // Additional tracking for login forms
                        if (possibleLogin) {
                            window._loginState.attempts++; // Use loginState.attempts instead of window._loginAttempts.count
                            window._loginState.lastAttemptTime = Date.now(); // Use loginState.lastAttemptTime
                            // window._loginAttempts.loginForms.add(formId); // No need for loginForms set

                            window._trackAction('login_attempt', {
                                formId: formId,
                                attemptNumber: window._loginState.attempts, // Use loginState.attempts
                                timestamp: new Date().toISOString(),
                                url: window.location.href
                            });
                        }
                    });

                    // Enhanced scroll tracking with throttling - no changes
                    let scrollTimeout;
                    let lastScrollPercent = -1;
                    document.addEventListener('scroll', (e) => {
                        clearTimeout(scrollTimeout);
                        scrollTimeout = setTimeout(() => {
                            const scrollPercent = Math.round((window.scrollY / (document.body.scrollHeight - window.innerHeight)) * 100);
                            // Only track if percentage changed significantly (by 5% or more)
                            if (isNaN(scrollPercent) || Math.abs(scrollPercent - lastScrollPercent) < 5) return;

                            lastScrollPercent = scrollPercent;
                            window._trackAction('scroll', {
                                position: window.scrollY,
                                percent: scrollPercent
                            });
                        }, 500);
                    });

                    // Track page visibility changes - no changes
                    document.addEventListener('visibilitychange', () => {
                        window._trackAction('visibility', {
                            visible: !document.hidden
                        });
                    });

                    // Track page load - no changes
                    window._trackAction('pageload', {
                        title: document.title,
                        referrer: document.referrer,
                        loadTime: performance.now()
                    });

                    // Enhanced button tracking with event delegation for better performance - no changes
                    document.addEventListener('click', (e) => {
                        // Using event delegation instead of attaching listeners to each button
                        let button = null;
                        let target = e.target;

                        // Find the button element in the event path
                        while (target && target !== document.body) {
                            if (target.tagName === 'BUTTON' ||
                                (target.tagName === 'INPUT' && (target.type === 'button' || target.type === 'submit')) ||
                                target.getAttribute('role') === 'button') {
                                button = target;
                                break;
                            }
                            target = target.parentNode;
                        }

                        if (button) {
                            const buttonText = button.textContent?.trim() || button.value || '';
                            const buttonDetails = {
                                element: button.tagName.toLowerCase(),
                                text: buttonText,
                                id: button.id || '',
                                name: button.name || '',
                                type: button.type || '',
                                role: button.getAttribute('role') || '',
                                'aria-label': button.getAttribute('aria-label') || '',
                                'data-testid': button.getAttribute('data-testid') || '',
                                disabled: button.disabled || false,
                                position: {
                                    x: e.pageX,
                                    y: e.pageY,
                                    viewport: {
                                        x: e.clientX,
                                        y: e.clientY
                                    }
                                },
                                classes: button.classList.length > 0 ? Array.from(button.classList) : [],
                                attributes: Array.from(button.attributes).map(attr => ({
                                    name: attr.name,
                                    value: attr.value
                                }))
                            };

                            window._trackAction('button_click', buttonDetails);
                        }
                    }, true);

                    // ----- Enhanced Interactive Element Hover Tracking with throttling ----- - no changes
                    let hoverThrottleTimer = null;
                    let lastHoveredElement = null;

                    function trackInteractiveElement(e) {
                        if (hoverThrottleTimer) clearTimeout(hoverThrottleTimer);

                        hoverThrottleTimer = setTimeout(() => {
                            const target = e.target;

                            // Skip if it's the same element as before
                            if (target === lastHoveredElement) return;
                            lastHoveredElement = target;

                            if (isInteractiveCandidate(target) && quickVisibilityCheck(target)) {
                                // Generate a simple XPath-like string (for demo purposes)
                                const tag = target.tagName.toLowerCase();
                                const id = target.id ? ('#' + target.id) : '';
                                window._trackAction('interactive_hover', {
                                    element: tag,
                                    identifier: id,
                                    text: target.textContent?.trim() || ''
                                });
                            }
                        }, 300); // 300ms throttle for hover events
                    }
                    // Listen for mouseover events to detect interactive elements
                    document.addEventListener('mouseover', trackInteractiveElement, { passive: true });
                    // ----------------------------------------------------------

                    // Enhanced button click tracking with DOM service integration - optimized - no changes
                    document.addEventListener('click', async (e) => {
                        if (e.target.matches('button, input[type="button"], input[type="submit"], [role="button"]')) {
                            console.log('Enhanced Button Click Listener TRIGGERED!'); // BASIC LOG - CONFIRM BUTTON CLICK LISTENER {
                            requestAnimationFrame(async () => {
                                const target = e.target;
                                const rect = target.getBoundingClientRect();
                                const viewport = {
                                    scrollX: window.scrollX,
                                    scrollY: window.scrollY,
                                    width: window.innerWidth,
                                    height: window.innerHeight
                                };
                                const coordinates = {
                                    topLeft: { x: rect.left, y: rect.top },
                                    topRight: { x: rect.right, y: rect.top },
                                    bottomLeft: { x: rect.left, y: rect.bottom },
                                    bottomRight: { x: rect.right, y: rect.bottom },
                                    center: {
                                        x: rect.left + rect.width / 2,
                                        y: rect.top + rect.height / 2
                                    },
                                    width: rect.width,
                                    height: rect.height
                                };
                                const styles = window.getComputedStyle(target);
                                const buttonText = target.textContent?.trim() || target.value || '';
                                const elementContext = await getSurroundingContext(target, 3);
                                const textualContext = getTextualContext(e.target);
                                window._trackAction('button_click', {
                                    element: target.tagName.toLowerCase(),
                                    text: buttonText,
                                    id: target.id || '',
                                    name: target.name || '',
                                    type: target.type || '',
                                    role: target.getAttribute('role') || '',
                                    'aria-label': target.getAttribute('aria-label') || '',
                                    'data-testid': target.getAttribute('data-testid') || '',
                                    disabled: target.disabled || false,
                                    viewport: viewport,
                                    coordinates: coordinates,
                                    styles: { ...styles },
                                    state: {
                                        focused: document.activeElement === target,
                                        disabled: target.disabled,
                                        checked: target.checked,
                                        selected: target.selected,
                                    },
                                    xpath: getXPath(target),
                                    cssPath: getCssPath(target),
                                    elementContext: elementContext,
                                    textualContext: textualContext
                                });

                                checkAuthStateChange();
                            });
                        }
                    }, { passive: true });// Use passive listener for better performance

                    // XPath generation helper - memoized for performance - no changes
                    const xpathCache = new Map();
                    function getXPath(element) {
                        // Check cache first
                        if (xpathCache.has(element)) {
                            return xpathCache.get(element);
                        }

                        const idx = (sib, name) => sib
                            ? idx(sib.previousElementSibling, name || sib.localName) + (sib.localName == name)
                            : 1;
                        const segments = elm => { // Modified segments function for robustness
                            if (!elm || elm.nodeType !== Node.ELEMENT_NODE) { // ADDED check for Element Node Type
                                return ['']; // Return empty array for non-element nodes
                            }
                            return elm.id && document.getElementById(elm.id) === elm
                                ? [`//*[@id="${elm.id}"]`]
                                : [...segments(elm.parentNode), `${elm.localName}[${idx(elm)}]`];
                        };


                        const result = segments(element).join('/');
                        xpathCache.set(element, result);
                        return result;
                    }

                    // CSS Path generation helper - memoized for performance - no changes
                    const cssPathCache = new Map();
                    function getCssPath(element) {
                        // Check cache first
                        if (cssPathCache.has(element)) {
                            return cssPathCache.get(element);
                        }

                        const path = [];
                        while (element.parentElement) {
                            let selector = element.tagName.toLowerCase();
                            if (element.id) {
                                selector += `#${element.id}`;
                                path.unshift(selector);
                                break;
                            } else {
                                let sibling = element;
                                let nth = 1;
                                while (sibling.previousElementSibling) {
                                    sibling = sibling.previousElementSibling;
                                    if (sibling.tagName === element.tagName) nth++;
                                }
                                if (nth > 1) selector += `:nth-of-type(${nth})`;
                            }
                            path.unshift(selector);
                            element = element.parentElement;
                        }

                        const result = path.join(' > ');
                        cssPathCache.set(element, result);
                        return result;
                    }

                    // Clear caches periodically to prevent memory leaks - no changes
                    setInterval(() => {
                        xpathCache.clear();
                        cssPathCache.clear();
                        cache.visibilityStatus.clear();
                        // We don't clear interactiveElements cache as those rarely change
                    }, 60000); // Clear caches every minute

                    // Add these to the existing network monitoring code in _setup_tracking - no changes
                    const loginIndicators = {
                        urls: ['/login', '/auth', '/signin', '/oauth', '/api/auth', '/token', '/api/login'],
                        headers: ['authorization', 'x-auth-token', 'x-access-token', 'bearer'],
                        bodyKeys: ['username', '/email', 'password', 'token', 'code', 'access_token'],
                        responseKeys: ['token', 'access_token', 'id_token', 'auth', 'session'],
                        successStatusCodes: [200, 201, 202, 204]
                    };

                    // Enhanced request analysis - no changes
                    async function analyzeRequest(request, body) {
                        const url = request.url.toLowerCase();

                        if (loginIndicators.excludeUrls.some(u => url.includes(u))) { // Exclude telemetry and similar URLs
                            return false;
                        }

                        const headers = Array.from(request.headers.entries());

                        // More specific and focused checks
                        const isAuthRequest =
                            loginIndicators.urls.some(u => url.includes(u)) ||
                            loginIndicators.headers.some(h => headers.some(([key]) => key.toLowerCase().includes(h))) ||
                            (body && loginIndicators.bodyKeys.some(k => body.toLowerCase().includes(k)));

                        return isAuthRequest;
                    }

                    // Enhanced response analysis - no changes
                    async function analyzeResponse(response, url) {
                        try {
                            const clonedResponse = response.clone();
                            const text = await clonedResponse.text();
                            let json;
                            try {
                                json = JSON.parse(text);
                            } catch (e) {
                                json = null;
                            }

                            // Check for success indicators in response
                            const hasAuthToken =
                                response.headers.has('authorization') ||
                                response.headers.has('x-auth-token') ||
                                (json && loginIndicators.responseKeys.some(key =>
                                    json[key] || (typeof json === 'string' && json.includes(key))
                                ));

                            return {
                                isSuccess: loginIndicators.successStatusCodes.includes(response.status) && hasAuthToken,
                                status: response.status,
                                headers: Array.from(response.headers.entries()),
                                body: json
                            };
                        } catch (e) {
                            console.debug('Error analyzing response:', e);
                            return {
                                isSuccess: loginIndicators.successStatusCodes.includes(response.status),
                                status: response.status,
                                headers: Array.from(response.headers.entries())
                            };
                        }
                    }

                    // Modified Fetch API interception - no changes
                    const originalFetch = window.fetch;
                    window.fetch = async (...args) => {
                        const request = args[0] instanceof Request ? args[0] : new Request(...args);
                        const clonedRequest = request.clone();

                        try {
                            const body = await clonedRequest.text();
                            const isAuthRequest = await analyzeRequest(request, body);
                            const isLogoutRequest = isLogoutUrl(request.url); 

                            if (isAuthRequest) {
                                trackLoginAttempt(request.url, request.method, body);

                                const response = await originalFetch(...args);
                                const responseAnalysis = await analyzeResponse(response.clone(), request.url);

                                if (responseAnalysis.isSuccess) {
                                    window._loginState.currentSession.isLoggedIn = true;
                                    window._loginState.currentSession.loginTime = new Date().toISOString();
                                    window._trackAction('login_success_network', {
                                        timestamp: new Date().toISOString(),
                                        url: request.url,
                                        method: request.method,
                                        responseData: responseAnalysis
                                    });
                                } else if (isLogoutRequest) { // New logout request handling
                                    trackLogoutAttempt(request.url, request.method, body); // Track logout attempt
                                    const response = await originalFetch(...args);
                                    handleLogoutResponse(request.url, response.clone().status); // Handle logout response
                                    return response;
                                } 
                                else {
                                    window._trackAction('login_failure_network', {
                                        timestamp: new Date().toISOString(),
                                        url: request.url,
                                        method: request.method,
                                        status: responseAnalysis.status
                                    });
                                }

                                return response;
                            }

                            return originalFetch(...args);
                        } catch (e) {
                            console.debug('Error in fetch intercept:', e);
                            return originalFetch(...args);
                        }
                    };

                    // Add SPA history monitoring - no changes
                    window.addEventListener('popstate', checkAuthStateChange);
                    const originalPushState = history.pushState;
                    const originalReplaceState = history.replaceState;

                    history.pushState = function() {
                        originalPushState.apply(this, arguments);
                        checkAuthStateChange();
                    };

                    history.replaceState = function() {
                        originalReplaceState.apply(this, arguments);
                        checkAuthStateChange();
                    };

                    async function checkAuthStateChange() {
                        const currentUrl = window.location.href;

                        // Check if we've navigated to a protected route
                        if (window._loginState.currentSession.isLoggedIn === false) {
                            const protectedRoutePatterns = ['/dashboard', '/account', '/profile', '/app/'];
                            const isProtectedRoute = protectedRoutePatterns.some(pattern =>
                                currentUrl.toLowerCase().includes(pattern)
                            );

                            if (isProtectedRoute) {
                                // We've accessed a protected route - likely means we're logged in
                                window._loginState.currentSession.isLoggedIn = true;
                                window._loginState.currentSession.loginTime = new Date().toISOString();
                                window._trackAction('login_detected_route', {
                                    timestamp: new Date().toISOString(),
                                    url: currentUrl
                                });
                            }
                        }
                    }

                    // Add LocalStorage/SessionStorage monitoring - no changes
                    const storageKeys = ['token', 'auth', 'session', 'user'];

                    const originalSetItem = Storage.prototype.setItem;
                    Storage.prototype.setItem = function(key, value) {
                        const storageType = this === localStorage ? 'localStorage' : 'sessionStorage';

                        // Check if this might be an auth token being set
                        if (storageKeys.some(k => key === k)) {
                            window._loginState.currentSession.isLoggedIn = true;
                            window._loginState.currentSession.loginTime = new Date().toISOString();
                            window._trackAction('login_detected_storage', {
                                timestamp: new Date().toISOString(),
                                storageType: storageType,
                                key: key,
                            });
                            console.log('Login Detected (Storage - Strict Key Match):', storageType, key);
                        } else {
                            console.debug('Storage setItem - Non-login related key:', storageType, key);
                        }

                        originalSetItem.apply(this, arguments);
                    };

                window._use_openai_login_check = true;
                window.pythonCheckLoginStatusWithOpenAI = async (fullPrompt) => { // Updated function
                    console.log('JS: Calling pythonCheckLoginStatusWithOpenAI with prompt...');
                    try {
                        const result = await window.check_login_status_openai(fullPrompt); // Call the exposed Python function DIRECTLY
                        console.log('JS: pythonCheckLoginStatusWithOpenAI result:', result);
                        return result;
                    } catch (error) {
                        console.log('JS: Error calling pythonCheckLoginStatusWithOpenAI:', error);
                        return false;
                    }
                };

                async function getSurroundingContext(element, depth = 2) { // Add depth parameter
                    if (!element || depth <= 0) return null;

                    let context = {
                        self: getElementInfo(element), // Info about the element itself
                        parent: getElementInfo(element.parentElement),
                        previousSibling: getElementInfo(element.previousElementSibling),
                        nextSibling: getElementInfo(element.nextElementSibling)
                    };

                    if (depth > 1 && element.parentElement) {
                        context.grandparent = await getSurroundingContext(element.parentElement, depth - 1); // Recursive call
                    }
                    return context;
                }
                function getTextualContext(element, levelsUp = 1, levelsDown = 1, siblingLevels = 1) {
                    if (!element) return {};
                    const context = {};

                    // Text from parent and ancestors
                    let current = element.parentElement;
                    for (let i = 0; i < levelsUp && current; i++) {
                        context[`parent_level_${i+1}_text`] = current.textContent?.trim().substring(0, 250);
                        current = current.parentElement;
                    }

                    // Text from children
                    const childrenText = [];
                    for (let i = 0; i < levelsDown; i++) {
                        element.querySelectorAll('*').forEach(child => { // Get all descendants
                        childrenText.push(child.textContent?.trim().substring(0, 100)); // Limit text per child
                        });
                    }
                    context['children_text'] = childrenText.filter(Boolean).join('; ').substring(0, 500); // Combine and limit

                    // Text from siblings (previous and next at siblingLevels deep)
                    let prevSibling = element.previousElementSibling;
                    for (let i = 0; i < siblingLevels && prevSibling; i++) {
                        context[`prev_sibling_level_${i+1}_text`] = prevSibling.textContent?.trim().substring(0, 250);
                        prevSibling = prevSibling.previousElementSibling;
                    }
                    let nextSibling = element.nextElementSibling;
                    for (let i = 0; i < siblingLevels && nextSibling; i++) {
                        context[`next_sibling_level_${i+1}_text`] = nextSibling.textContent?.trim().substring(0, 250);
                        nextSibling = nextSibling.nextElementSibling;
                    }
                    return context;
                }

                function getElementInfo(el) {
                    if (!el || !el.tagName) return null;
                    return {
                        tagName: el.tagName.toLowerCase(),
                        className: el.className,
                        id: el.id,
                        textContent: el.textContent?.trim().substring(0, 250) // First 50 chars
                    };
                }
            }
        """