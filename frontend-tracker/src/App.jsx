import { useState } from 'react';

import Calibration from './Calibration';
import SessionReplay from './SessionReplay';
import { useGazeTracker } from './useGazeTracker';
import { useTracker } from './useTracker';

function TrackingApp() {
  const [isCalibrated, setIsCalibrated] = useState(false);

  useTracker();
  const {
    ready,
    providerMode,
    requiresCalibration,
    calibrationTargets,
    startLocalCalibration,
    submitLocalCalibrationSample,
  } = useGazeTracker(isCalibrated);
  const trackingActive = providerMode === 'local_bridge' ? ready && !requiresCalibration : isCalibrated;
  const calibrationPoints = calibrationTargets.length ? calibrationTargets : undefined;

  return (
    <div className="App" style={{ fontFamily: 'Arial, sans-serif', minHeight: '100vh' }}>
      {ready && requiresCalibration && !isCalibrated && (
        <Calibration
          points={calibrationPoints}
          title={
            providerMode === 'local_bridge'
              ? 'Kalibracja desktop eye-trackera'
              : 'Kalibracja browser eye-trackera'
          }
          subtitle={
            providerMode === 'local_bridge'
              ? 'Patrz na punkt i kliknij, aby zapisać próbkę dla lokalnego agenta.'
              : 'Patrz dokładnie na punkt przed kliknięciem.'
          }
          onPointCapture={async (point) => {
            if (providerMode !== 'local_bridge') {
              return;
            }
            if (!calibrationTargets.length) {
              await startLocalCalibration();
            }
            await submitLocalCalibrationSample({
              target_x: point.x,
              target_y: point.y,
              screen_x: point.x * window.innerWidth,
              screen_y: point.y * window.innerHeight,
            });
          }}
          onComplete={() => setIsCalibrated(true)}
        />
      )}

      <div style={{ padding: '20px', maxWidth: '1000px', margin: '0 auto' }}>
        <header style={{ marginBottom: '40px', textAlign: 'center', borderBottom: '1px solid #eee', paddingBottom: '20px' }}>
          <h1>Test Uzytecznosci + Eye Tracking</h1>
          <p style={{ color: trackingActive ? 'green' : 'orange', fontWeight: 'bold' }}>
            Status: {trackingActive ? 'TRACKING AKTYWNY (Oczy + Mysz)' : 'Wymagana kalibracja...'}
          </p>
          <p>
            Gaze source: <code>{providerMode}</code>
          </p>
          <p>
            Replay recorded sessions at <code>?replay=session_id</code>
          </p>
          <p>
            Or open the replay browser at <code>?mode=replay</code>
          </p>
        </header>

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '20px', marginBottom: '60px' }}>
          <div
            id="section-blue"
            style={{
              flex: 1,
              padding: '40px',
              background: '#e3f2fd',
              borderRadius: '12px',
              textAlign: 'center',
              border: '2px solid #2196f3',
            }}
          >
            <h2 id="header-blue">Opcja Niebieska</h2>
            <p>Spójrz tutaj, jeśli lubisz kolor nieba.</p>
            <button id="btn-blue" style={btnStyle}>Wybieram Niebieski</button>
          </div>

          <div
            id="section-red"
            style={{
              flex: 1,
              padding: '40px',
              background: '#ffebee',
              borderRadius: '12px',
              textAlign: 'center',
              border: '2px solid #f44336',
            }}
          >
            <h2 id="header-red">Opcja Czerwona</h2>
            <p>Spójrz tutaj, jeśli wolisz ogień.</p>
            <button id="btn-red" style={{ ...btnStyle, background: '#f44336' }}>Wybieram Czerwony</button>
          </div>
        </div>

        <div style={{ maxWidth: '500px', margin: '0 auto', background: '#f9f9f9', padding: '30px', borderRadius: '8px' }}>
          <h3>Zostaw opinię</h3>
          <form
            id="feedback-form"
            onSubmit={(event) => {
              event.preventDefault();
              alert('Wyslano!');
            }}
          >
            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>Twój email:</label>
              <input type="email" name="email" id="input-email" placeholder="test@test.pl" style={inputStyle} />
            </div>

            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>Wiadomość:</label>
              <textarea name="message" id="input-msg" style={{ ...inputStyle, height: '80px' }} />
            </div>

            <button type="submit" style={{ ...btnStyle, width: '100%', background: '#4caf50' }}>Wyślij opinię</button>
          </form>
        </div>

        <div style={{ marginTop: '80px', textAlign: 'center', color: '#888' }}>
          <p>Przewiń w dół, aby przetestować tracking scrollowania</p>
          <div style={{ height: '600px', background: 'linear-gradient(to bottom, #fff, #eee)' }} />
          <button id="btn-footer" style={{ ...btnStyle, background: '#333' }}>Znalazłeś stopkę!</button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const params = new URLSearchParams(window.location.search);
  const replaySessionId = params.get('replay');
  const mode = params.get('mode');

  if (replaySessionId || mode === 'replay') {
    return <SessionReplay />;
  }

  return <TrackingApp />;
}

const btnStyle = {
  padding: '12px 24px',
  fontSize: '16px',
  color: 'white',
  background: '#2196f3',
  border: 'none',
  borderRadius: '6px',
  cursor: 'pointer',
  marginTop: '15px',
  fontWeight: 'bold',
};

const inputStyle = {
  width: '100%',
  padding: '10px',
  borderRadius: '4px',
  border: '1px solid #ccc',
  boxSizing: 'border-box',
};

export default App;
