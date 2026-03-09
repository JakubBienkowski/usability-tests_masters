import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';

const Popup = () => {
  const [status, setStatus] = useState('Łączenie...');

  useEffect(() => {
    // Sprawdź stan połączenia z background.js
    chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
      setStatus(response.status);
    });
  }, []);

  return (
    <div style={{ width: '250px', padding: '15px' }}>
      <h2>UX Research Tool</h2>
      <p>Status: <b>{status}</b></p>
      <button onClick={() => alert("Wysyłam logi...")}>
        Wymuś wysyłkę danych
      </button>
    </div>
  );
};

createRoot(document.getElementById('root')).render(<Popup />);