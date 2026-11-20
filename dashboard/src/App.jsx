import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api, isAuthenticated, onAuthExpired } from './api'
import Layout from './components/Layout'
import {
  AcceptInvitation,
  ForgotPassword,
  Login,
  ResetPassword,
  Signup,
  VerifyEmail,
} from './pages/AccountPages'
import Analytics from './pages/Analytics'
import Appointments from './pages/Appointments'
import CallDetail from './pages/CallDetail'
import Calls from './pages/Calls'
import Dashboard from './pages/Dashboard'
import Leads from './pages/Leads'
import Properties from './pages/Properties'
import Settings from './pages/Settings'
import Usage from './pages/Usage'

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}

function AppRoutes() {
  const [authed, setAuthed] = useState(isAuthenticated())

  useEffect(() => onAuthExpired(() => setAuthed(false)), [])

  async function logout() {
    try {
      await api.logout()
    } finally {
      setAuthed(false)
    }
  }

  return (
    <Routes>
      <Route path="/login" element={authed ? <Navigate to="/" replace /> : <Login onLogin={() => setAuthed(true)} />} />
      <Route path="/signup" element={authed ? <Navigate to="/" replace /> : <Signup />} />
      <Route path="/verify-email" element={authed ? <Navigate to="/" replace /> : <VerifyEmail />} />
      <Route path="/forgot-password" element={authed ? <Navigate to="/" replace /> : <ForgotPassword />} />
      <Route path="/reset-password" element={authed ? <Navigate to="/" replace /> : <ResetPassword />} />
      <Route path="/accept-invitation" element={authed ? <Navigate to="/" replace /> : <AcceptInvitation />} />
      <Route element={authed ? <Layout onLogout={logout} /> : <Navigate to="/login" replace />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/calls" element={<Calls />} />
          <Route path="/calls/:callId" element={<CallDetail />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/properties" element={<Properties />} />
          <Route path="/appointments" element={<Appointments />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/usage" element={<Usage />} />
      </Route>
      <Route path="*" element={<Navigate to={authed ? '/' : '/login'} replace />} />
    </Routes>
  )
}
