import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext.jsx'
import { SettingsProvider } from './context/SettingsContext.jsx'
import Login from './pages/Login.jsx'
import ChildHome from './pages/ChildHome.jsx'
import LessonPage from './pages/LessonPage.jsx'
import ParentDashboard from './pages/ParentDashboard.jsx'
import SubjectPage from './pages/SubjectPage.jsx'
import IntroPage from './pages/IntroPage.jsx'
import Curriculum from './pages/Curriculum.jsx'
import Settings from './pages/Settings.jsx'

function Guard({ role: need, children }) {
  const { token, role } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (need && role !== need) return <Navigate to={role === 'parent' ? '/parent' : '/'} replace />
  return children
}

export default function App() {
  return (
    <SettingsProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/" element={<Guard><ChildHome /></Guard>} />
            <Route path="/subject/:subject" element={<Guard><SubjectPage /></Guard>} />
            <Route path="/subject/:subject/intro/:sectionId" element={<Guard><IntroPage /></Guard>} />
            <Route path="/lesson/:id" element={<Guard><LessonPage /></Guard>} />
            <Route path="/parent" element={<Guard role="parent"><ParentDashboard /></Guard>} />
            <Route path="/parent/curriculum" element={<Guard role="parent"><Curriculum /></Guard>} />
            <Route path="/parent/settings" element={<Guard role="parent"><Settings /></Guard>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </SettingsProvider>
  )
}
