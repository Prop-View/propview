import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { api, setAuth } from '../api'
import { Login, Signup } from './AccountPages'

vi.mock('../api', () => ({
  api: {
    login: vi.fn(),
    signup: vi.fn(),
  },
  setAuth: vi.fn(),
}))

describe('account pages', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => cleanup())

  it('signs in with an agency slug, email, and password and stores the short-lived session', async () => {
    const user = { id: 8, email: 'owner@example.test', display_name: 'Owner', role: 'owner' }
    api.login.mockResolvedValue({
      access_token: 'session-token',
      expires_at: '2030-01-01T00:00:00Z',
      user,
    })
    const onLogin = vi.fn()

    render(
      <MemoryRouter>
        <Login onLogin={onLogin} />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText('Agency slug'), { target: { value: 'sample-agency' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'owner@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse battery' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))

    await waitFor(() => expect(api.login).toHaveBeenCalledWith(
      'sample-agency',
      'owner@example.test',
      'correct horse battery',
    ))
    expect(setAuth).toHaveBeenCalledWith('sample-agency', 'session-token', user, '2030-01-01T00:00:00Z')
    expect(onLogin).toHaveBeenCalledOnce()
  })

  it('creates an agency account and reports that email verification is required', async () => {
    api.signup.mockResolvedValue({ tenant_slug: 'sample-agency', status: 'verification_required' })

    render(
      <MemoryRouter>
        <Signup />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText('Agency name'), { target: { value: 'Sample Realty' } })
    fireEvent.change(screen.getByLabelText('Agency slug'), { target: { value: 'sample-agency' } })
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Agency Owner' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'owner@example.test' } })
    fireEvent.change(screen.getByLabelText('Password (at least 12 characters)'), { target: { value: 'correct horse battery' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))

    await waitFor(() => expect(api.signup).toHaveBeenCalledWith({
      tenant_slug: 'sample-agency',
      tenant_name: 'Sample Realty',
      owner_name: 'Agency Owner',
      email: 'owner@example.test',
      password: 'correct horse battery',
    }))
    expect((await screen.findByRole('status')).textContent).toContain(
      'Check owner@example.test for a verification link.',
    )
  })
})
