public class TestApp {
    public static void main(String[] args) {
        businessLogic();
    }

    public static void businessLogic() {
        String data = "secret";
        if (data.equals("secret")) {
            System.out.println("Access Granted");
        }
    }
}
