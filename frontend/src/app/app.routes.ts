import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'chat' },
  { path: 'chat', title: 'Chat · Document Assistant', loadComponent: () => import('./features/chat/chat.page').then((m) => m.ChatPage) },
  {
    path: 'documents',
    title: 'Documents · Document Assistant',
    loadComponent: () => import('./features/documents/documents.page').then((m) => m.DocumentsPage),
  },
  {
    path: 'history',
    title: 'History · Document Assistant',
    loadComponent: () => import('./features/history/history.page').then((m) => m.HistoryPage),
  },
  { path: '**', redirectTo: 'chat' },
];
