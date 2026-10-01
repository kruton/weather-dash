import './App.css'
import { Routes, Route, useNavigate } from 'react-router-dom';
import Weather from './components/Weather/Weather'
import Fleet from './components/Fleet/Fleet'
import { useState } from 'react';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/weather" element={<Weather />} />
      <Route path="/admin/*" element={<Fleet />} />
    </Routes>
  )
}

const Home = () => {
  const navigate = useNavigate();
  const [lat, setLat] = useState('');
  const [long, setLong] = useState('');
  const [name, setName] = useState<string | null>(null);

  const handleSubmit = (e: { preventDefault: () => void; }) => {
    e.preventDefault();
    let url = `/weather?lat=${lat}&long=${long}`;
    if (name !== null) {
      url += `&name=${encodeURIComponent(name)}`;
    }
    navigate(url);
  };

  return (
    <>
      <div className="home">
        <h1>Weather Dashboard Creator</h1>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Location Name (optional)"
            value={name || ''}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            type="number"
            placeholder="Latitude"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
          />
          <input
            type="number"
            placeholder="Longitude"
            value={long}
            onChange={(e) => setLong(e.target.value)}
          />
          <button type="submit">Create Dashboard</button>
        </form>
      </div>
      <a href="/admin">Manage panels</a>
    </>
  );
}

export default App
