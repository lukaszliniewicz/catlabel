import React from 'react';
import Sidebar from './components/Sidebar';
import CanvasArea from './components/CanvasArea';

function App() {
  return (
    <div className="flex h-screen w-full bg-gray-100 overflow-hidden">
      <Sidebar />
      <CanvasArea />
    </div>
  );
}

export default App;
