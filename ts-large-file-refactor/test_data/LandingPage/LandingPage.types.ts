export interface User {
  id: string;
  name: string;
  email: string;
  role: 'admin' | 'user' | 'guest';
}

export interface Plan {
  id: string;
  name: string;
  price: number;
  features: string[];
}

export interface LandingPageProps {
  user?: User;
  plans: Plan[];
}
