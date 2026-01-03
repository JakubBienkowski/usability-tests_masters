import React, { useState } from 'react';

import { useTracker } from './useTracker';
import { useGazeTracker } from './useGazeTracker';
import Calibration from './Calibration';

function App() {
  // Stan kalibracji - czy użytkownik zakończył klikanie w kropki?
  // średnio ale działa
  const [isCalibrated, setIsCalibrated] = useState(false);

  //  Uruchamiamy tracker myszki, kliknięć i formularzy (działa od razu)
  useTracker();

  // Uruchamiamy tracker wzroku
  // długo to trwa, trzeba wykminić jak lepiej to ładować
  const { ready } = useGazeTracker(isCalibrated);

  return (
    <div className="App" style={{ fontFamily: 'Arial, sans-serif', minHeight: '100vh' }}>


      {ready && !isCalibrated && (
        <Calibration onComplete={() => setIsCalibrated(true)} />
      )}

      {/* AI slop  */}
      <div style={{ padding: '20px', maxWidth: '1000px', margin: '0 auto' }}>
        
        <header style={{ marginBottom: '40px', textAlign: 'center', borderBottom: '1px solid #eee', paddingBottom: '20px' }}>
          <h1>Test Użyteczności + Eye Tracking</h1>
          <p style={{ color: isCalibrated ? 'green' : 'orange', fontWeight: 'bold' }}>
            Status: {isCalibrated ? "TRACKING AKTYWNY (Oczy + Mysz)" : "Wymagana kalibracja..."}
          </p>
        </header>

        {/* Test Eye Trackera: Dwie kolumny, żeby sprawdzić czy wykrywa gdzie patrzysz */}
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '20px', marginBottom: '60px' }}>
          
          <div id="section-blue" style={{ 
              flex: 1, padding: '40px', background: '#e3f2fd', 
              borderRadius: '12px', textAlign: 'center', border: '2px solid #2196f3'
          }}>
            <h2 id="header-blue">Opcja Niebieska</h2>
            <p>Spójrz tutaj, jeśli lubisz kolor nieba.</p>
            <button id="btn-blue" style={btnStyle}>Wybieram Niebieski</button>
          </div>

          <div id="section-red" style={{ 
              flex: 1, padding: '40px', background: '#ffebee', 
              borderRadius: '12px', textAlign: 'center', border: '2px solid #f44336'
          }}>
            <h2 id="header-red">Opcja Czerwona</h2>
            <p>Spójrz tutaj, jeśli wolisz ogień.</p>
            <button id="btn-red" style={{...btnStyle, background: '#f44336'}}>Wybieram Czerwony</button>
          </div>

        </div>

        {/* Test Trackera Formularzy */}
        <div style={{ maxWidth: '500px', margin: '0 auto', background: '#f9f9f9', padding: '30px', borderRadius: '8px' }}>
          <h3>Zostaw opinię</h3>
          <form 
            id="feedback-form"
            onSubmit={(e) => { e.preventDefault(); alert("Wysłano!"); }}
          >
            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>Twój email:</label>
              <input type="email" name="email" id="input-email" placeholder="test@test.pl" style={inputStyle} />
            </div>

            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>Wiadomość:</label>
              <textarea name="message" id="input-msg" style={{...inputStyle, height: '80px'}}></textarea>
            </div>

            <button type="submit" style={{...btnStyle, width: '100%', background: '#4caf50'}}>Wyślij opinię</button>
          </form>
        </div>

        {/* Test Scrolla */}
        <div style={{ marginTop: '80px', textAlign: 'center', color: '#888' }}>
          <p>⬇️ Przewiń w dół, aby przetestować tracking scrollowania ⬇️</p>
          <div style={{ height: '600px', background: 'linear-gradient(to bottom, #fff, #eee)' }}></div>
          <button id="btn-footer" style={{...btnStyle, background: '#333'}}>Znalazłeś stopkę!</button>
        </div>

      </div>
    </div>
  );
}

// Proste style CSS-in-JS dla czytelności
const btnStyle = {
  padding: '12px 24px',
  fontSize: '16px',
  color: 'white',
  background: '#2196f3',
  border: 'none',
  borderRadius: '6px',
  cursor: 'pointer',
  marginTop: '15px',
  fontWeight: 'bold'
};

const inputStyle = {
  width: '100%',
  padding: '10px',
  borderRadius: '4px',
  border: '1px solid #ccc',
  boxSizing: 'border-box'
};

export default App;