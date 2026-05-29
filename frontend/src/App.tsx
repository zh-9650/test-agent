import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import TaskCreate from './pages/TaskCreate';
import Monitor from './pages/Monitor';
import Report from './pages/Report';
import TaskHistory from './pages/TaskHistory';
import MemoryManager from './pages/MemoryManager';

function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: '1rem', borderBottom: '1px solid #ddd' }}>
        <Link to="/" style={{ marginRight: '1rem' }}>创建任务</Link>
        <Link to="/history" style={{ marginRight: '1rem' }}>历史任务</Link>
        <Link to="/memory">AI 记忆管理</Link>
      </nav>
      <Routes>
        <Route path="/" element={<TaskCreate />} />
        <Route path="/monitor/:taskId" element={<Monitor />} />
        <Route path="/report/:taskId" element={<Report />} />
        <Route path="/history" element={<TaskHistory />} />
        <Route path="/memory" element={<MemoryManager />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
