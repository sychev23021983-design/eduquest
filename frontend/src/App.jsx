import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext.jsx'
import Login from './pages/Login.jsx'
import ChildHome from './pages/ChildHome.jsx'
import LessonPage from './pages/LessonPage.jsx'
import ParentDashboard from './pages/ParentDashboard.jsx'
import LessonEditor from './pages/LessonEditor.jsx'

function Guard({ role: need, children }) {
  const { token, role } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (need && role !== need) return <Navigate to={role === 'parent' ? '/parent' : '/'} replace />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Guard><ChildHome /></Guard>} />
          <Route path="/lesson/:id" element={<Guard><LessonPage /></Guard>} />
          <Route path="/parent" element={<Guard role="parent"><ParentDashboard /></Guard>} />
          <Route path="/parent/lesson/new" element={<Guard role="parent"><LessonEditor /></Guard>} />
          <Route path="/parent/lesson/:id/edit" element={<Guard role="parent"><LessonEditor /></Guard>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
