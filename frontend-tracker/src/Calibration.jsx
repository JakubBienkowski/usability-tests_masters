import React, { useState } from 'react';

const Calibration = ({ onComplete }) => {
  const [clicks, setClicks] = useState(0);
  const points = [
    { top: '10%', left: '10%' },
    { top: '10%', left: '90%' },
    { top: '50%', left: '50%' },
    { top: '90%', left: '10%' },
    { top: '90%', left: '90%' }
  ];

  const handlePointClick = (e) => {
    // WebGazer uczy się przy każdym kliknięciu
    // Musimy kliknąć parę razy w każdy punkt dla precyzji, 
    // ale w tym POC zrobimy po 1 kliknięciu w 5 punktów
    const next = clicks + 1;
    setClicks(next);
    if (next >= points.length) {
      alert("Kalibracja zakończona!");
      onComplete();
    }
  };

  if (clicks >= points.length) return null;

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.9)', zIndex: 9999,
      display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'white'
    }}>
      <h3>Kliknij w czerwoną kropkę ({clicks + 1}/5) <br/> Patrz dokładnie na kursor!</h3>
      
      <div 
        onClick={handlePointClick}
        style={{
          position: 'absolute',
          width: '30px', height: '30px',
          background: 'red', borderRadius: '50%',
          cursor: 'pointer', border: '2px solid white',
          top: points[clicks].top,
          left: points[clicks].left,
          transform: 'translate(-50%, -50%)'
        }}
      />
    </div>
  );
};

export default Calibration;