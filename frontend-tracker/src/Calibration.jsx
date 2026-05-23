import React, { useState } from 'react';

const defaultPoints = [
  { x: 0.1, y: 0.1 },
  { x: 0.9, y: 0.1 },
  { x: 0.5, y: 0.5 },
  { x: 0.1, y: 0.9 },
  { x: 0.9, y: 0.9 },
];

const Calibration = ({
  onComplete,
  onPointCapture,
  title = 'Kliknij w czerwoną kropkę',
  subtitle = 'Patrz dokładnie na punkt przed kliknięciem.',
  points = defaultPoints,
}) => {
  const [clicks, setClicks] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handlePointClick = async () => {
    if (submitting) return;
    setError('');
    setSubmitting(true);
    const point = points[clicks];
    try {
      await onPointCapture?.(point);
    } catch (captureError) {
      setError(captureError?.message || 'Nie udało się zapisać próbki kalibracyjnej.');
      setSubmitting(false);
      return;
    }
    const next = clicks + 1;
    setClicks(next);
    if (next >= points.length) {
      onComplete();
    }
    setSubmitting(false);
  };

  if (clicks >= points.length) return null;

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.9)', zIndex: 9999,
      display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'white'
    }}>
      <div style={{ textAlign: 'center' }}>
        <h3>{title} ({clicks + 1}/{points.length})</h3>
        <p>{subtitle}</p>
        {error && <p style={{ color: '#ff8a80' }}>{error}</p>}
      </div>
      
      <div 
        onClick={handlePointClick}
        style={{
          position: 'absolute',
          width: '30px', height: '30px',
          background: 'red', borderRadius: '50%',
          cursor: submitting ? 'wait' : 'pointer', border: '2px solid white',
          top: `${(points[clicks].y ?? 0.5) * 100}%`,
          left: `${(points[clicks].x ?? 0.5) * 100}%`,
          transform: 'translate(-50%, -50%)'
        }}
      />
    </div>
  );
};

export default Calibration;
