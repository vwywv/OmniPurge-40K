import java.io.*;

public class ResourceApp {
    public static void main(String[] args) throws Exception {
        FileInputStream fis = new FileInputStream("non_existent.txt");
        // 故意不使用 try-with-resources，看 AI 是否能优化为圣洁的写法
        int content = fis.read();
        System.out.println(content);
    }
}
