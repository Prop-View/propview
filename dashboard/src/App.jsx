import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { clearAuth, isAuthenticated } from './api'
import Layout from './components/Layout'
import Analytics from './pages/Analytics'
import Appointments from './pages/Appointments'
import CallDetail from './pages/CallDetail'
import Calls from './pages/Calls'
import Dashboard from './pages/Dashboard'
import Leads from './pages/Leads'
import Login from './pages/Login'
import Properties from './pages/Properties'
import Settings from './pages/Settings'

export default function App() {
  const [authed, setAuthed] = useState(isAuthenticated())

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout onLogout={() => { clearAuth(); setAuthed(false) }} />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/calls" element={<Calls />} />
          <Route path="/calls/:callId" element={<CallDetail />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/properties" element={<Properties />} />
          <Route path="/appointments" element={<Appointments />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
