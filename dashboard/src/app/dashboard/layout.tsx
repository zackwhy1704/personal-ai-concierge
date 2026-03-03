'use client'
import { useEffect } from 'react'
import Sidebar from '@/components/Sidebar'
import { api } from '@/lib/api'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    api.initTokenRefresh()
  }, [])

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 p-8">{children}</main>
    </div>
  )
}
