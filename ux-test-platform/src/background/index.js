// background/index.js
const WS_URL = "ws://localhost:8000/ws";
let socket = null;
let sessionId = null;

async function initSession() {
    const data = await chrome.storage.local.get(['session_id']);
    sessionId = data.session_id || `sess_${Math.random().toString(36).substr(2, 9)}`;
    await chrome.storage.local.set({ session_id: sessionId });
    connect();
}

function connect() {
    socket = new WebSocket(`${WS_URL}/${sessionId}`);
    
    socket.onopen = () => console.log("Połączono z backendem");
    socket.onclose = () => setTimeout(connect, 3000); // Automatyczne wznawianie
    socket.onerror = (err) => console.error("WebSocket error:", err);
}

// Odbieranie danych z content-scriptu (DOM, kliknięcia)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            ...request,
            url: sender.tab?.url,
            timestamp: new Date().toISOString()
        }));
    }
});

initSession();