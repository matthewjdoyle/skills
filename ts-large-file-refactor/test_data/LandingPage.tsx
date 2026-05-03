import React, { useState } from 'react';

// Lots of types
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

// Hardcoded constants
const MAX_RETRIES = 3;
const API_BASE_URL = 'https://api.example.com/v1';
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Some helper functions
const validateEmail = (email: string) => EMAIL_REGEX.test(email);
const formatPrice = (price: number) => `$${price.toFixed(2)}`;

export const LandingPage: React.FC<LandingPageProps> = ({ user, plans }) => {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  
  // Hardcoded content strings
  const heroTitle = "Welcome to the Best Product Ever";
  const heroSubtitle = "We help you achieve your goals faster and better than anyone else. Sign up today and get 50% off your first month.";
  const ctaButtonText = "Get Started Now";
  const featuresTitle = "Why Choose Us?";
  const featuresList = [
    "Lightning fast performance",
    "Bank-grade security",
    "24/7 customer support",
    "Easy integration with your existing tools"
  ];
  
  const handleSubscribe = async () => {
    if (!validateEmail(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    
    setIsSubmitting(true);
    setError('');
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      alert("Thanks for subscribing!");
      setEmail('');
    } catch (err) {
      setError("An error occurred. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="landing-page">
      {/* Header Section */}
      <header className="header">
        <div className="logo">MyBrand</div>
        <nav>
          <ul>
            <li><a href="#features">Features</a></li>
            <li><a href="#pricing">Pricing</a></li>
            {user ? (
              <li><a href="#dashboard">Dashboard</a></li>
            ) : (
              <li><a href="#login">Login</a></li>
            )}
          </ul>
        </nav>
      </header>

      {/* Hero Section */}
      <section className="hero">
        <div className="hero-content">
          <h1>{heroTitle}</h1>
          <p>{heroSubtitle}</p>
          <div className="cta-form">
            <input 
              type="email" 
              placeholder="Enter your email address" 
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button onClick={handleSubscribe} disabled={isSubmitting}>
              {isSubmitting ? "Submitting..." : ctaButtonText}
            </button>
            {error && <p className="error">{error}</p>}
          </div>
        </div>
        <div className="hero-image">
          <img src="https://example.com/images/hero-illustration.png" alt="Hero Illustration" />
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="features">
        <h2>{featuresTitle}</h2>
        <div className="feature-grid">
          {featuresList.map((feature, index) => (
            <div key={index} className="feature-card">
              <div className="icon">🚀</div>
              <h3>{feature}</h3>
              <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="pricing">
        <h2>Simple, transparent pricing</h2>
        <p>No hidden fees. Cancel anytime.</p>
        <div className="pricing-grid">
          {plans.map(plan => (
            <div key={plan.id} className="pricing-card">
              <h3>{plan.name}</h3>
              <div className="price">
                <span className="amount">{formatPrice(plan.price)}</span>
                <span className="period">/month</span>
              </div>
              <ul className="plan-features">
                {plan.features.map((feature, index) => (
                  <li key={index}>{feature}</li>
                ))}
              </ul>
              <button className="plan-button">Choose {plan.name}</button>
            </div>
          ))}
        </div>
      </section>

      {/* Footer Section */}
      <footer className="footer">
        <div className="footer-content">
          <div className="footer-column">
            <h4>Product</h4>
            <ul>
              <li><a href="#">Features</a></li>
              <li><a href="#">Pricing</a></li>
              <li><a href="#">Case Studies</a></li>
              <li><a href="#">Reviews</a></li>
            </ul>
          </div>
          <div className="footer-column">
            <h4>Company</h4>
            <ul>
              <li><a href="#">About Us</a></li>
              <li><a href="#">Careers</a></li>
              <li><a href="#">Blog</a></li>
              <li><a href="#">Contact</a></li>
            </ul>
          </div>
          <div className="footer-column">
            <h4>Legal</h4>
            <ul>
              <li><a href="#">Privacy Policy</a></li>
              <li><a href="#">Terms of Service</a></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <p>&copy; 2026 MyBrand Inc. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
};
