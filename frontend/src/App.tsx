import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import TaskCreate from './pages/TaskCreate';
import Monitor from './pages/Monitor';
import Report from './pages/Report';
import TaskHistory from './pages/TaskHistory';
import MemoryManager from './pages/MemoryManager';
import AnalysisPackagePage from './pages/AnalysisPackage';

function App() {
  return (
    <BrowserRouter>
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        {/* Modern Navigation Header */}
        <header style={{
          position: 'sticky',
          top: 0,
          zIndex: 50,
          background: 'rgba(8, 9, 14, 0.75)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid var(--border-color)',
          padding: '0.75rem 2rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          {/* Logo / Title */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'var(--primary-gradient)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold',
              color: '#fff',
              fontSize: '1.1rem',
              boxShadow: '0 0 15px rgba(99, 102, 241, 0.4)'
            }}>
              S
            </div>
            <span style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              background: 'linear-gradient(to right, #fff, #94a3b8)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              letterSpacing: '-0.02em'
            }}>
              Smart Test Agent
            </span>
          </div>

          {/* Navigation Links */}
          <nav style={{ display: 'flex', gap: '0.5rem' }}>
            <NavLink
              to="/"
              className={({ isActive }) => `btn ${isActive ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
            >
              创建任务
            </NavLink>
            <NavLink
              to="/history"
              className={({ isActive }) => `btn ${isActive ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
            >
              历史任务
            </NavLink>
            <NavLink
              to="/memory"
              className={({ isActive }) => `btn ${isActive ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
            >
              AI 知识库
            </NavLink>
          </nav>
        </header>

        {/* Main Content Area */}
        <div style={{ flex: 1, padding: '2rem 1rem' }}>
          <Routes>
            <Route path="/" element={<TaskCreate />} />
            <Route path="/monitor/:taskId" element={<Monitor />} />
            <Route path="/report/:taskId" element={<Report />} />
            <Route path="/analysis/:taskId" element={<AnalysisPackagePage />} />
            <Route path="/history" element={<TaskHistory />} />
            <Route path="/memory" element={<MemoryManager />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

export default App;
